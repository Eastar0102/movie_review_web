"""데모용 시드 데이터 생성 스크립트.

한국 영화 50편과 각 영화당 리뷰 10개(총 500개)를 백엔드 API로 등록한다.
리뷰는 영화별 감상 포인트 + 문장 템플릿으로 생성하며, 감성 분석은 백엔드가 수행한다.
이미 등록된 제목은 건너뛰므로 여러 번 실행해도 중복되지 않는다.

    python scripts/seed_data.py                  # 기본 http://localhost:8000
    python scripts/seed_data.py --workers 8      # 동시 요청 수 조절 (기본 4)
    python scripts/seed_data.py --limit 10       # 앞에서 10편만 등록
    API_URL=http://... python scripts/seed_data.py

메타데이터(개봉일·감독·장르·포스터)는 위키데이터/위키백과에서 수집해 검증한 값이다.
"""

import argparse
import os
import random
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")
REVIEWS_PER_MOVIE = 10
RANDOM_SEED = 20260727  # 실행할 때마다 같은 리뷰가 나오도록 고정

AUTHORS = [
    "김민준", "이서연", "박지훈", "최수아", "정하윤", "강도윤", "윤채원", "임지우",
    "한서준", "오예린", "신도현", "조은우", "배시우", "황서아", "문가온", "서지호",
    "노아린", "유건우", "백다인", "송민서", "전유진", "고태윤", "구하람", "심재원",
    "표지안", "하윤슬", "양세림", "채민호", "도현우", "안소율",
]

# {p:은/는} 자리에는 영화별 감상 포인트가, {director}/{title}/{genre}에는 영화 정보가 들어간다.
POSITIVE_TEMPLATES = [
    "{p:은/는} 지금 봐도 훌륭하다. 오랜만에 제대로 몰입한 영화.",
    "{p:이/가} 특히 인상적이었다. 완성도가 높은 수작.",
    "{p:을/를} 보고 나서 한참을 생각하게 됐다. 여운이 길게 남는다.",
    "{p:은/는} 몇 번을 다시 봐도 새롭다. 인생영화로 꼽고 싶다.",
    "{p:이/가} 이 영화의 백미다. 강력 추천합니다.",
    "{p:은/는} 정말 좋았고 배우들 연기도 완벽했다.",
    "{p:을/를} 위해서라도 극장에서 볼 만한 영화.",
    "{p:이/가} 기대 이상이었다. 두 시간이 순식간에 지나갔다.",
    "{p:은/는} 두고두고 회자될 만하다. 각본이 탄탄해서 좋았다.",
    "{p:이/가} 마음에 깊게 남았다. 묵직하면서도 따뜻한 작품.",
    "{p:을/를} 이렇게 풀어낼 줄은 몰랐다. 신선하고 훌륭했다.",
    "{p:은/는} 다시 봐도 감탄이 나온다. 미술과 촬영이 빛난다.",
    "{p:이/가} 몰입을 끌어올린다. 지루할 틈이 없었다.",
    "{p:을/를} 떠올리면 아직도 소름이 돋는다. 완성도 높은 걸작.",
    "{p:은/는} 이 장르에서 손꼽을 만하다. 아주 만족스러웠다.",
    "{p:이/가} 인상 깊어서 주변에 추천하고 다녔다.",
    "{p:을/를} 보며 오랜만에 울었다. 감정선이 잘 살아 있다.",
    "{p:은/는} 감독의 장기가 잘 드러나는 부분. 훌륭한 연출이었다.",
    "{director} 감독 작품 중에서도 손에 꼽을 만하다. 만족스러웠다.",
    "{title}만의 분위기가 확실하다. 오랜만에 좋은 영화를 봤다.",
    "{genre} 좋아하면 후회하지 않을 영화. 추천합니다.",
    "기대 없이 봤다가 제대로 몰입했다. {title:은/는} 확실히 완성도가 높다.",
    "{title:을/를} 다시 봐도 좋았다. 배우들 연기가 정말 훌륭하다.",
    "{director} 감독다운 연출이 곳곳에서 빛난다. 명작이다.",
]
NEGATIVE_TEMPLATES = [
    "{p:은/는} 좋았지만 전체적으로는 늘어져서 아쉬웠다.",
    "{p:이/가} 과하게 반복돼 후반부는 지루했다.",
    "{p:을/를} 기대하고 봤는데 생각보다 별로였다.",
    "{p:은/는} 억지스러워서 몰입이 깨졌다.",
    "{p:이/가} 취향을 심하게 탄다. 나에게는 불편했다.",
    "{p:을/를} 빼면 남는 게 많지 않다. 아쉬운 작품.",
    "{p:은/는} 뻔한 클리셰라 실망스러웠다.",
    "{p:이/가} 산만해서 이야기에 집중하기 어려웠다.",
    "{p:을/를} 보는 내내 불편했다. 재관람은 어려울 것 같다.",
    "{p:은/는} 기대에 못 미쳤다. 평가가 과한 것 같다.",
    "{p:이/가} 어색해서 아쉬움이 크게 남는다.",
    "{p:을/를} 위해 두 시간을 쓰기엔 아깝다는 생각이 들었다.",
    "{director} 감독의 다른 작품이 훨씬 나았다. 실망스러웠다.",
    "{genre} 팬이라면 아쉬울 수 있다. 기대만큼은 아니었다.",
    "설정이 작위적이라 끝까지 몰입이 안 됐다. {title:은/는} 나에게 별로였다.",
    "중반부가 지나치게 늘어져서 지루했다. {genre} 중에서도 아쉬운 편.",
]

MOVIES = [
    {
        "title": "기생충",
        "release_date": "2019-05-30",
        "director": "봉준호",
        "genre": "드라마, 스릴러",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/5/53/Parasite_%282019_film%29.png",
        "points": ["계단 하나로 계급을 보여주는 연출", "반지하와 저택을 오가는 미술", "송강호와 이선균의 대비"],
    },
    {
        "title": "올드보이",
        "release_date": "2003-11-21",
        "director": "박찬욱",
        "genre": "미스터리, 스릴러",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/6/67/Oldboykoreanposter.jpg",
        "points": ["장도리 롱테이크", "최민식의 광기 어린 연기", "충격적인 반전"],
    },
    {
        "title": "부산행",
        "release_date": "2016-07-20",
        "director": "연상호",
        "genre": "액션, 공포",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/9/95/Train_to_Busan.jpg",
        "points": ["기차라는 한정된 공간의 활용", "마동석 캐릭터의 활약", "쉴 틈 없는 초반 전개"],
    },
    {
        "title": "살인의 추억",
        "release_date": "2003-05-02",
        "director": "봉준호",
        "genre": "드라마, 범죄",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/0/01/Salinui-chueok-south-korean-movie-poster-md.jpg",
        "points": ["논두렁에서 시작하는 첫 장면", "송강호와 김상경의 대비", "정면을 응시하는 마지막 얼굴"],
    },
    {
        "title": "괴물",
        "release_date": "2006-07-27",
        "director": "봉준호",
        "genre": "드라마, 공포",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/5/55/The_Host_film_poster.jpg",
        "points": ["한강 둔치를 가로지르는 괴물의 등장", "뿔뿔이 흩어진 가족이 뭉치는 과정", "재난 속 소시민의 시선"],
    },
    {
        "title": "마더",
        "release_date": "2009-05-28",
        "director": "봉준호",
        "genre": "드라마, 미스터리",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/8/80/Mother_film_poster.jpg",
        "points": ["김혜자의 눈빛 연기", "춤으로 시작해 춤으로 끝나는 구성", "모성을 뒤집어 보는 방식"],
    },
    {
        "title": "설국열차",
        "release_date": "2013-08-01",
        "director": "봉준호",
        "genre": "드라마, 스릴러",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/b/b4/Snowpiercer_poster.jpg",
        "points": ["칸을 하나씩 돌파하는 구조", "틸다 스윈튼의 기괴한 캐릭터", "열차로 압축한 계급 은유"],
    },
    {
        "title": "친절한 금자씨",
        "release_date": "2005-07-29",
        "director": "박찬욱",
        "genre": "드라마, 스릴러",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/c/c8/Lady_Vengeance_poster.png",
        "points": ["이영애의 붉은 아이섀도", "차갑게 정돈된 화면 톤", "복수를 완성하는 방식"],
    },
    {
        "title": "아가씨",
        "release_date": "2016-06-01",
        "director": "박찬욱",
        "genre": "드라마, 스릴러",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/a/a2/The_Handmaiden_film.png",
        "points": ["저택의 미술과 의상", "몇 번씩 뒤집히는 구성", "김민희와 김태리의 호흡"],
    },
    {
        "title": "헤어질 결심",
        "release_date": "2022-06-29",
        "director": "박찬욱",
        "genre": "드라마, 로맨스",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/8/82/Decision_to_Leave_film_poster.jpg",
        "points": ["탕웨이와 박해일 사이의 미묘한 거리", "안개로 뒤덮인 후반부", "대사 한 줄 한 줄의 결"],
    },
    {
        "title": "공동경비구역 JSA",
        "release_date": "2000-09-09",
        "director": "박찬욱",
        "genre": "드라마, 스릴러",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/7/7f/Jsa.movist.jpg",
        "points": ["초코파이를 나누는 장면", "군사분계선을 사이에 둔 우정", "이병헌과 송강호의 연기"],
    },
    {
        "title": "신세계",
        "release_date": "2013-02-21",
        "director": "박훈정",
        "genre": "드라마, 범죄",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/3/3f/New_World2013-poster.jpg",
        "points": ["엘리베이터 액션 시퀀스", "황정민이 만든 정청 캐릭터", "마지막까지 조여드는 긴장"],
    },
    {
        "title": "범죄도시",
        "release_date": "2017-10-03",
        "director": "강윤성",
        "genre": "액션, 범죄",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/7/72/Criminal_City_%28%EB%B2%94%EC%A3%84%EB%8F%84%EC%8B%9C%29.jpg",
        "points": ["마동석의 시원한 액션", "윤계상이 보여준 악역", "실화를 살린 설정"],
    },
    {
        "title": "극한직업",
        "release_date": "2019-01-23",
        "director": "이병헌",
        "genre": "액션, 코미디",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/d/d7/Extreme_Job_poster.jpg",
        "points": ["수원왕갈비통닭 설정", "쉴 새 없이 몰아치는 대사", "형사 다섯 명의 팀워크"],
    },
    {
        "title": "명량",
        "release_date": "2014-07-30",
        "director": "김한민",
        "genre": "액션, 사극",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/3/3a/Battle_of_Myeongryang_poster.jpg",
        "points": ["해전 장면의 스케일", "최민식이 연기한 이순신", "후반부 전투 시퀀스"],
    },
    {
        "title": "국제시장",
        "release_date": "2014-12-17",
        "director": "윤제균",
        "genre": "드라마",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/0/04/Ode_to_My_Father.jpg",
        "points": ["한 세대를 관통하는 이야기", "황정민의 노년 연기", "가족을 향한 시선"],
    },
    {
        "title": "도둑들",
        "release_date": "2012-07-25",
        "director": "최동훈",
        "genre": "액션, 범죄",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/4/48/The_Thieves.jpg",
        "points": ["화려한 캐스팅의 앙상블", "홍콩에서 펼쳐지는 와이어 액션", "케이퍼 무비 특유의 리듬"],
    },
    {
        "title": "암살",
        "release_date": "2015-07-22",
        "director": "최동훈",
        "genre": "드라마, 스릴러",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/5/57/Assassination_%28poster%29.jpg",
        "points": ["전지현의 저격 장면", "1930년대를 살린 미술과 의상", "마지막 재판 시퀀스"],
    },
    {
        "title": "베테랑",
        "release_date": "2015-08-05",
        "director": "류승완",
        "genre": "드라마, 액션",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/4/45/Veteran_%282015_film%29.jpg",
        "points": ["황정민과 유아인의 대립", "명동 한복판 추격전", "속 시원한 결말"],
    },
    {
        "title": "부당거래",
        "release_date": "2010-10-28",
        "director": "류승완",
        "genre": "범죄 스릴러",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/c/c7/The_Unjust_film_poster.jpg",
        "points": ["황정민이 내뱉는 대사", "얽히고설킨 권력 관계", "씁쓸하게 남는 결말"],
    },
    {
        "title": "밀정",
        "release_date": "2016-09-07",
        "director": "김지운",
        "genre": "드라마",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/e/ea/The_Age_of_Shadows_%28film%29.jpg",
        "points": ["기차 안에서 이어지는 시퀀스", "송강호의 이중적인 태도", "차갑게 가라앉은 촬영"],
    },
    {
        "title": "좋은 놈, 나쁜 놈, 이상한 놈",
        "release_date": "2008-05-24",
        "director": "김지운",
        "genre": "액션, 웨스턴",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/7/7a/The_Good%2C_the_Bad%2C_the_Weird_film_poster.jpg",
        "points": ["만주 벌판을 내달리는 추격 시퀀스", "세 배우의 뚜렷한 캐릭터", "귀에 남는 음악"],
    },
    {
        "title": "달콤한 인생",
        "release_date": "2005-04-01",
        "director": "김지운",
        "genre": "드라마, 액션",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/6/64/A_Bittersweet_Life_Poster.jpg",
        "points": ["이병헌의 마지막 독백", "느와르다운 조명과 미술", "군더더기 없는 액션의 리듬"],
    },
    {
        "title": "장화, 홍련",
        "release_date": "2003-06-13",
        "director": "김지운",
        "genre": "드라마, 공포",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/2/21/A_Tale_of_Two_Sisters_film.jpg",
        "points": ["붉은 벽지가 인상적인 미술", "임수정과 문근영의 호흡", "서서히 조여오는 공포"],
    },
    {
        "title": "곡성",
        "release_date": "2016-05-11",
        "director": "나홍진",
        "genre": "스릴러, 공포",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/e/eb/The_Wailing_%28film%29.png",
        "points": ["굿을 벌이는 시퀀스", "무엇도 확신할 수 없는 구성", "곽도원이 보여준 부성애"],
    },
    {
        "title": "추격자",
        "release_date": "2008-02-14",
        "director": "나홍진",
        "genre": "액션, 범죄 스릴러",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/4/4d/The_Chaser_film_poster.jpg",
        "points": ["골목을 내달리는 추격 장면", "하정우의 서늘한 표정", "김윤석의 절박함"],
    },
    {
        "title": "황해",
        "release_date": "2010-12-22",
        "director": "나홍진",
        "genre": "스릴러, 액션",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/0/04/The_Yellow_Sea-p3.jpg",
        "points": ["하정우의 생존 연기", "김윤석의 압도적인 존재감", "거칠고 날것 같은 액션"],
    },
    {
        "title": "왕의 남자",
        "release_date": "2005-12-29",
        "director": "이준익",
        "genre": "드라마, 코미디",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/9/91/The_King_and_the_Clown_movie_poster.jpg",
        "points": ["줄타기 장면", "이준기의 강렬한 등장", "광대들이 던지는 풍자"],
    },
    {
        "title": "사도",
        "release_date": "2015-09-16",
        "director": "이준익",
        "genre": "드라마, 사극",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/9/9c/The_Throne_%28film%29.jpg",
        "points": ["뒤주를 둘러싼 시퀀스", "송강호와 유아인의 부자 관계", "정갈한 궁중 미술"],
    },
    {
        "title": "동주",
        "release_date": "2016-02-17",
        "director": "이준익",
        "genre": "드라마",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/6/6c/Dongju_The_Portrait_of_a_Poet_poster.jpeg",
        "points": ["흑백으로 담아낸 화면", "강하늘이 읊는 시", "송몽규와의 대비"],
    },
    {
        "title": "택시운전사",
        "release_date": "2017-08-02",
        "director": "장훈",
        "genre": "드라마, 액션",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/2/23/A_Taxi_Driver.jpg",
        "points": ["송강호가 보여주는 변화", "광주로 들어가는 길", "후반 택시 추격 장면"],
    },
    {
        "title": "변호인",
        "release_date": "2013-12-18",
        "director": "양우석",
        "genre": "드라마",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/b/b5/The_Attorney_poster.jpg",
        "points": ["법정 변론 장면", "송강호의 열연", "실화가 주는 무게"],
    },
    {
        "title": "7번방의 선물",
        "release_date": "2013-01-23",
        "director": "이환경",
        "genre": "드라마, 코미디",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/4/4c/Miracle_in_Cell_No._7_poster.jpg",
        "points": ["류승룡과 갈소원의 호흡", "7번방 사람들의 사연", "후반 법정 장면"],
    },
    {
        "title": "광해, 왕이 된 남자",
        "release_date": "2012-09-13",
        "director": "추창민",
        "genre": "드라마, 정치",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/8/85/Gwanghae.jpg",
        "points": ["이병헌의 1인 2역", "궁중 생활을 그린 유머", "마지막 이별 장면"],
    },
    {
        "title": "관상",
        "release_date": "2013-09-11",
        "director": "한재림",
        "genre": "드라마",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/f/fb/The_Face_Reader_poster.jpg",
        "points": ["관상을 풀어내는 송강호", "수양대군의 등장", "궁중 정치극다운 긴장"],
    },
    {
        "title": "내부자들",
        "release_date": "2015-11-19",
        "director": "우민호",
        "genre": "드라마, 범죄",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/c/c2/Inside_Men_%28film%29_poster.jpeg",
        "points": ["이병헌이 쏟아내는 대사", "권력 카르텔의 민낯", "복수가 주는 쾌감"],
    },
    {
        "title": "남산의 부장들",
        "release_date": "2020-01-22",
        "director": "우민호",
        "genre": "드라마, 스릴러",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/0/0b/The_Man_Standing_Next_movie_poster%2C_Jan_2020.jpg",
        "points": ["이병헌의 절제된 연기", "10·26을 향해 조여드는 긴장", "차분한 미술과 촬영"],
    },
    {
        "title": "태극기 휘날리며",
        "release_date": "2004-02-03",
        "director": "강제규",
        "genre": "드라마, 액션",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/7/7a/Taegukgi_film_poster.jpg",
        "points": ["전투 장면의 규모", "장동건과 원빈의 형제 관계", "전쟁이 갈라놓는 사람들"],
    },
    {
        "title": "쉬리",
        "release_date": "1999-02-13",
        "director": "강제규",
        "genre": "드라마, 스릴러",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/f/f1/Shiri_Poster.jpg",
        "points": ["한국형 블록버스터의 출발점", "한석규와 최민식의 대결", "이별 장면의 음악"],
    },
    {
        "title": "신과함께: 죄와 벌",
        "release_date": "2017-12-20",
        "director": "김용화",
        "genre": "드라마, 판타지",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/9/95/Along_With_the_Gods_-_The_Two_Worlds.jpg",
        "points": ["지옥 재판이라는 설정", "차태현과 하정우의 호흡", "지옥을 구현한 CG"],
    },
    {
        "title": "82년생 김지영",
        "release_date": "2019-10-23",
        "director": "김도영",
        "genre": "드라마",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/9/9e/Kim_Ji-young_Born_1982_%28film%29.jpg",
        "points": ["정유미의 담담한 연기", "일상에 스며든 순간들", "원작이 던지는 질문"],
    },
    {
        "title": "벌새",
        "release_date": "2019-08-29",
        "director": "김보라",
        "genre": "드라마",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/8/87/House_of_Hummingbird_poster.jpg",
        "points": ["1994년의 공기", "은희와 영지 선생님의 관계", "담담하게 응시하는 화면"],
    },
    {
        "title": "파묘",
        "release_date": "2024-02-22",
        "director": "장재현",
        "genre": "스릴러, 공포",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/1/13/Exhuma_film_poster.jpg",
        "points": ["묘를 파는 초반 시퀀스", "최민식과 김고은의 호흡", "후반부의 방향 전환"],
    },
    {
        "title": "검은 사제들",
        "release_date": "2015-11-05",
        "director": "장재현",
        "genre": "드라마, 공포",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/d/d6/The_Priests_%28film%29_poster.jpeg",
        "points": ["구마 의식 장면", "김윤석과 강동원의 대비", "짧고 밀도 높은 전개"],
    },
    {
        "title": "서울의 봄",
        "release_date": "2023-11-22",
        "director": "김성수",
        "genre": "드라마, 스릴러",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/f/fc/12.12-_The_Day.jpg",
        "points": ["황정민이 만든 악역", "9시간을 압축한 긴장감", "정우성과의 대립 구도"],
    },
    {
        "title": "아수라",
        "release_date": "2016-09-12",
        "director": "김성수",
        "genre": "액션, 범죄 스릴러",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/e/e5/Asura_The_City_of_Madness_poster.jpeg",
        "points": ["정우성의 지친 얼굴", "황정민이 연기한 시장", "쉼 없이 몰아치는 폭력"],
    },
    {
        "title": "콘크리트 유토피아",
        "release_date": "2023-08-09",
        "director": "엄태화",
        "genre": "스릴러, 재난",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/a/ac/Concrete_Utopia.jpeg",
        "points": ["무너진 도시를 그린 미술", "이병헌이 보여준 광기", "아파트라는 소재"],
    },
    {
        "title": "밀양",
        "release_date": "2007-05-17",
        "director": "이창동",
        "genre": "드라마",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/4/4c/Secret_Sunshine.png",
        "points": ["전도연의 연기", "종교를 다루는 시선", "곁을 지키는 송강호"],
    },
    {
        "title": "버닝",
        "release_date": "2018-05-17",
        "director": "이창동",
        "genre": "드라마, 스릴러",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/4/45/Burning.png",
        "points": ["노을 앞에서 추는 춤 장면", "스티븐 연이 만든 미스터리", "끝까지 모호한 결말"],
    },
    {
        "title": "건축학개론",
        "release_date": "2012-03-22",
        "director": "이용주",
        "genre": "드라마, 로맨스",
        "poster_url": "https://upload.wikimedia.org/wikipedia/en/4/4d/Architecture_101_film_poster.jpg",
        "points": ["첫사랑의 기억을 되짚는 구성", "수지와 한가인이 이어 붙인 시간", "귀에 감기는 음악"],
    },
]

# 기존 데모 데이터(영화 3편)의 리뷰는 직접 작성한 문장을 그대로 유지한다.
HANDWRITTEN = {
    "기생충": [
        "계단 하나로 계급을 보여주는 연출이 정말 훌륭했다. 인생영화.",
        "배우들 연기가 모두 완벽했고 몰입도가 최고였어요.",
        "각본이 탄탄해서 두 시간이 순식간에 지나갔다. 강력 추천.",
        "후반부 전개가 충격적이었지만 여운이 오래 남는 걸작.",
        "메시지는 좋았지만 중반부가 조금 늘어져서 아쉬웠다.",
        "기대가 너무 컸던 탓인지 생각보다 별로였다.",
        "블랙코미디와 스릴러의 균형이 신선하고 훌륭했다.",
        "미술과 촬영이 빛나는 웰메이드 수작.",
        "결말이 불편해서 보고 나서 기분이 좋지 않았다.",
        "몇 번을 다시 봐도 새로운 디테일이 보이는 명작.",
    ],
    "올드보이": [
        "장도리 롱테이크는 지금 봐도 압도적이다. 명작.",
        "최민식의 연기가 미쳤다. 소름 돋는 몰입감.",
        "반전이 충격적이라 한동안 멍했다. 훌륭한 각본.",
        "잔인한 장면이 많아 보는 내내 불편했다.",
        "미장센이 아름답고 음악도 정말 좋았어요.",
        "이야기는 강렬하지만 취향을 심하게 탄다. 별로였다.",
        "복수 3부작 중 가장 완성도 높은 수작.",
        "20년이 지나도 회자되는 데는 이유가 있다. 추천.",
        "설정이 다소 억지스러워서 몰입이 깨졌다.",
        "여운이 길게 남는 인생영화 중 하나.",
    ],
    "부산행": [
        "초반부터 끝까지 긴장감이 유지되는 재미있는 영화.",
        "한국형 좀비물의 기준을 세운 작품. 훌륭했다.",
        "마동석 캐릭터가 최고였다. 통쾌하고 재밌었음.",
        "신파가 과해서 후반부는 조금 유치했다.",
        "속도감 있는 전개 덕분에 지루할 틈이 없었다.",
        "캐릭터들이 뻔한 클리셰라 아쉬웠다.",
        "기차라는 한정 공간을 잘 활용한 연출이 좋았다.",
        "CG가 어색한 장면이 몇 군데 있어 실망.",
        "가족애 코드가 따뜻해서 울었다. 추천합니다.",
        "오랜만에 극장에서 제대로 몰입한 영화.",
    ],
}

PLACEHOLDER = re.compile(r"\{(p|title|director|genre)(?::([^}]+))?\}")


def josa(word: str, pair: str) -> str:
    """받침 유무에 따라 조사를 붙인다. pair는 '받침있음/받침없음' 순서."""
    with_final, without_final = pair.split("/")
    last = word[-1]
    has_final = "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28
    return word + (with_final if has_final else without_final)


def render(template: str, movie: dict, point: str) -> str:
    """{p}/{title}/{director}/{genre} 자리를 채우고, ':조사'가 붙었으면 받침에 맞춰 조사도 붙인다."""
    values = {
        "p": point,
        "title": movie["title"],
        "director": movie["director"],
        "genre": movie["genre"].split(",")[0].strip(),
    }

    def replace(match):
        word = values[match.group(1)]
        return josa(word, match.group(2)) if match.group(2) else word

    return PLACEHOLDER.sub(replace, template)


def build_reviews(movie: dict, rng: random.Random) -> list[tuple[str, str]]:
    """영화 1편에 대한 (작성자, 리뷰) 10개를 만든다. 긍정 6~8개 + 나머지 부정."""
    if movie["title"] in HANDWRITTEN:
        contents = HANDWRITTEN[movie["title"]]
    else:
        positives = rng.randint(6, 8)
        picked = (rng.sample(POSITIVE_TEMPLATES, positives)
                  + rng.sample(NEGATIVE_TEMPLATES, REVIEWS_PER_MOVIE - positives))
        # 같은 감상 포인트가 몰리지 않도록 한 바퀴씩 순환하며 배분한다
        pool = []
        while len(pool) < len(picked):
            block = movie["points"][:]
            rng.shuffle(block)
            pool += block
        contents = [render(t, movie, pool.pop()) for t in picked]
        rng.shuffle(contents)
    return list(zip(rng.sample(AUTHORS, len(contents)), contents))


def main() -> None:
    parser = argparse.ArgumentParser(description="영화·리뷰 데모 데이터를 등록한다.")
    parser.add_argument("--workers", type=int, default=4, help="리뷰 등록 동시 요청 수 (기본 4)")
    parser.add_argument("--limit", type=int, default=None, help="등록할 영화 수 제한")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):  # 콘솔 인코딩 때문에 죽지 않도록
        sys.stdout.reconfigure(errors="replace")

    rng = random.Random(RANDOM_SEED)
    targets = MOVIES[: args.limit] if args.limit else MOVIES

    with httpx.Client(base_url=API_URL, timeout=180) as client:
        try:
            client.get("/")
        except httpx.HTTPError:
            sys.exit(f"백엔드({API_URL})에 연결할 수 없습니다. 서버를 먼저 실행하세요.")

        existing = {m["title"] for m in client.get("/movies", params={"limit": 200}).json()}
        todo = []
        for movie in targets:
            reviews = build_reviews(movie, rng)  # 건너뛰더라도 난수 흐름은 유지
            if movie["title"] in existing:
                print(f"[건너뜀] {movie['title']} (이미 등록됨)")
                continue
            todo.append((movie, reviews))

        if not todo:
            print("새로 등록할 영화가 없습니다.")
            return

        total = len(todo) * REVIEWS_PER_MOVIE
        print(f"영화 {len(todo)}편 / 리뷰 {total}개 등록을 시작합니다 "
              f"(동시 요청 {args.workers}개)\n")

        done = threading.Lock()
        counter = {"n": 0, "pos": 0}

        def post_review(job):
            movie_id, author, content = job
            res = client.post("/reviews",
                              json={"movie_id": movie_id, "author": author, "content": content})
            res.raise_for_status()
            result = res.json()
            with done:
                counter["n"] += 1
                counter["pos"] += result["sentiment"] == "positive"
                if counter["n"] % 25 == 0 or counter["n"] == total:
                    print(f"  리뷰 {counter['n']}/{total} 완료 "
                          f"(긍정 {counter['pos']})", flush=True)
            return result

        jobs = []
        for movie, reviews in todo:
            payload = {k: v for k, v in movie.items() if k != "points"}
            res = client.post("/movies", json=payload)
            res.raise_for_status()
            created = res.json()
            print(f"[영화] {created['title']} (ID={created['id']})")
            jobs += [(created["id"], author, content) for author, content in reviews]

        print()
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            list(pool.map(post_review, jobs))

        stats = client.get("/stats").json()
        print(f"\n완료: 전체 영화 {stats['movie_count']}편 / 리뷰 {stats['review_count']}개 / "
              f"평균 평점 {stats['avg_rating']} / 긍정 비율 {stats['positive_ratio']:.0%}")


if __name__ == "__main__":
    main()

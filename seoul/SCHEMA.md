# TourAPI 4.0 원본 데이터 스키마

한국관광공사 Tour API(TourAPI 4.0)에서 수집한 원본 JSON 파일의 필드 정의.

---

## 파일 최상위 구조

| 필드 | 타입 | 설명 |
|------|------|------|
| `region` | string | 수집 지역명 |
| `contentType` | string | 콘텐츠 유형 한국어명 |
| `contentTypeId` | string | 콘텐츠 유형 ID (아래 코드 참조) |
| `total` | integer | 전체 항목 수 |
| `items` | object[] | POI 항목 배열 |

## contentTypeId 코드

| ID | 유형 |
|----|------|
| 12 | 관광지 |
| 14 | 문화시설 |
| 15 | 축제공연행사 |
| 28 | 레포츠 |
| 32 | 숙박 |
| 38 | 쇼핑 |
| 39 | 음식점 |

---

## items[] 필드

| 필드 | 타입 | 설명 |
|------|------|------|
| `contentid` | string | 콘텐츠 고유 ID |
| `contenttypeid` | string | 콘텐츠 유형 ID |
| `title` | string | 장소명 |
| `addr1` | string | 주소 (도로명 또는 지번) |
| `addr2` | string | 주소 상세 (건물명 등) |
| `zipcode` | string | 우편번호 |
| `tel` | string | 전화번호 |
| `mapx` | string | 경도 (WGS84) |
| `mapy` | string | 위도 (WGS84) |
| `mlevel` | string | 지도 레벨 |
| `areacode` | string | 지역 코드 |
| `sigungucode` | string | 시군구 코드 |
| `lDongRegnCd` | string | 법정동 지역 코드 |
| `lDongSignguCd` | string | 법정동 시군구 코드 |
| `cat1` | string | 대분류 코드 |
| `cat2` | string | 중분류 코드 |
| `cat3` | string | 소분류 코드 |
| `lclsSystm1` | string | 분류 체계 1 |
| `lclsSystm2` | string | 분류 체계 2 |
| `lclsSystm3` | string | 분류 체계 3 |
| `firstimage` | string | 대표 이미지 URL (원본) |
| `firstimage2` | string | 대표 이미지 URL (썸네일) |
| `cpyrhtDivCd` | string | 저작권 구분 코드 |
| `createdtime` | string | 최초 등록 시각 (YYYYMMDDHHmmss) |
| `modifiedtime` | string | 최종 수정 시각 (YYYYMMDDHHmmss) |

---

## 주의 사항

- `mapx` / `mapy` 는 string 타입으로 저장됨. 사용 시 float 변환 필요.
- `firstimage` 가 빈 문자열(`""`)인 경우 이미지 없음을 의미.
- `addr1` 이 빈 문자열인 경우 주소 정보 미제공.
- `cat1~3`, `lclsSystm1~3` 코드 정의는 상위 디렉토리의 `lclsSystemCode.json` 참조.

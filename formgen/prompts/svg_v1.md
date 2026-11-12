서류 이미지를 같은 배치의 빈 SVG 서식으로 복원한다. SVG 하나만 출력한다.

1. 루트는 <svg xmlns="http://www.w3.org/2000/svg" width="794" height="1123" viewBox="0 0 794 1123">. 원본이 다른 비율이면 width, height, viewBox를 같은 비율로 지정한다. 단일 페이지.
2. 고정 문구는 <text x="..." y="..." font-size="..." font-family="Malgun Gothic">문구</text>로 유지한다. 선·칸은 rect/line/path 등 벡터 요소로 그린다. 글자를 path로 바꾸지 않는다. y는 텍스트 baseline이다. 줄바꿈은 별도의 text/tspan으로 명시한다.
3. 문서마다 채워지는 이름·주소·번호·날짜·금액·선택·직인·서명은 지운다. 은행 로고와 기관명·법정 문구는 고정 인쇄 문구로 유지한다. 이미지에 빈 기재란이 있어도 빠짐없이 필드로 표시한다.
4. 필드는 루트 바로 아래의 rect로 선언한다. 좌표는 viewBox 기준이며 transform을 쓰지 않는다.
   <rect data-field="applicant.name" data-label="성명" data-type="text" x="120" y="180" width="180" height="24" fill="none" stroke="none"/>
5. data-field는 문서 안에서 유일한 영문 소문자·숫자·밑줄·점 경로. 타입은 text/number/amount/date/checkbox/seal/signature. 전화·계좌·식별번호는 text, 수량은 number, 돈은 amount. 날짜의 년/월/일이 별도 칸이면 각각 number 필드로 나눌 수 있다.
6. 체크 묶음 하나는 checkbox 필드 하나로 만들고 data-options="신청|미신청"를 기록한다. 인쇄된 보기 글자와 빈 상자를 실제 text/rect로 따로 그린다. 서명·직인은 빈 영역으로 표시하고 실제 서명·도장은 그리지 않는다.
7. 허용 요소: svg,g,rect,line,polyline,polygon,path,circle,ellipse,text,tspan,title,desc. script/style/foreignObject/image/use/외부 참조/href/이벤트 속성/CSS class/style 속성/url() 금지. 스타일은 fill,stroke,font-size 같은 SVG presentation 속성으로 지정한다.
8. 필드 박스는 양수 크기이고 페이지 안에 있어야 한다. 루트 및 필드에는 transform을 쓰지 않는다. 표와 글자를 겹치거나 페이지 밖에 두지 않는다.
9. 원본에 반복 행이 있으면 보이는 행을 유지하고 각 행의 필드 키를 구별한다. 값 자리 rect는 보이지 않는 주석이며 빈 문서의 선·문구는 따로 그려야 한다.

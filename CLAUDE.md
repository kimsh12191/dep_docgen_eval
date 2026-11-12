Read `README.md` first. 이 브랜치(template-html)는 문서 이미지 → HTML 템플릿 꾸러미. `main` 의 SVG 방식과 섞지 않는다.
규칙을 바꾸면 `tplgen/prompts/template_v1.md`(규격)와 `tplgen/package.py`(검사)를 함께 고치고 `python -m unittest discover -s tests` 를 돌린다.
통과 기준은 `tplgen/check.py` 의 `PASS_RULE` 한 곳. 실서류 이미지는 사내 모델 주소에만 보낸다. 확인 안 한 것을 확인했다고 쓰지 않는다.

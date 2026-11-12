"""깨끗한 문서 그림 → 스캔한 것처럼 (조금 기울고, 종이색·얼룩·잡음·흐림·jpeg). 시험 입력을 만들 때 쓴다.
  python tools/scanify.py samples/hf153.png samples/hf153_scan.jpg [--seed 0] [--angle 1.2]
"""
import argparse
import random

import numpy as np
from PIL import Image, ImageFilter


def scanify(src, dst, seed=0, angle=1.2):
    rng = np.random.default_rng(seed)
    random.seed(seed)
    im = Image.open(src).convert("L")
    im = im.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=255).filter(ImageFilter.GaussianBlur(0.8))
    a = np.asarray(im).astype(float)
    h, w = a.shape
    yy, xx = np.mgrid[0:h, 0:w]
    shade = 1 - 0.10 * (xx / w) - 0.05 * np.sin(yy / h * 3.1)            # 한쪽이 어두운 조명 얼룩
    a = 235 - (255 - a) * 0.82                                             # 종이는 회색빛, 잉크는 덜 검게
    a = a * shade + rng.normal(0, 6, a.shape)                              # 잡음
    specks = rng.random(a.shape) < 0.0004                                  # 먼지 점
    a[specks] -= 90
    Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).save(dst, quality=55)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--angle", type=float, default=1.2)
    a = ap.parse_args()
    scanify(a.src, a.dst, a.seed, a.angle)

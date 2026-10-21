"""
make_qr.py - QR code for the live demo link (slide 5).

Run:   python qr/make_qr.py https://1jjl7.github.io/mikyal-demo/
Out:   qr/mikyal-qr.png (for the slide), qr/mikyal-qr.svg (for print)
Needs: pip install qrcode pillow
"""

import sys
from pathlib import Path

import qrcode
import qrcode.image.svg

HERE = Path(__file__).parent
url = sys.argv[1] if len(sys.argv) > 1 else "https://1jjl7.github.io/mikyal-demo/"

q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=24, border=4)
q.add_data(url)
q.make(fit=True)
q.make_image(fill_color="#0f2e2c", back_color="white").save(HERE / "mikyal-qr.png")
qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, border=4).save(HERE / "mikyal-qr.svg")
print(f"saved {HERE / 'mikyal-qr.png'} -> {url}")

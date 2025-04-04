import base64
from PIL import Image as im
import numpy as np
import argparse
from tcam import TCam
import sys
from ironblack import ironblack_palette

camera = TCam()
res = camera.connect("192.168.4.1")
print(f"success with the response : {res}")

outfile = "hello12.png"

img = camera.get_image()
dimg = base64.b64decode(img["radiometric"])
mv = memoryview(dimg).cast("H")

print("Figuring out image min/max for mapping to palette")
imgmin = 65535
imgmax = 0

for i in mv.tolist():
    if i < imgmin:
        imgmin = i
    if i > imgmax:
        imgmax = i

delta = imgmax - imgmin
print(f"Max val is {imgmax}, Min val is {imgmin}, Delta is {delta}")

# now we form the 8 bit range from the min and delta.  This allows us to bracket the 16 bit data into
# an 8 bit range, and then use the 8 bits to look up the palette data for the pixel value.
transformed = []
for i in mv:
    val = int((i - imgmin) * 255 / delta)

    if val > 255:
        transformed.append(ironblack_palette[255])
    else:
        transformed.append(ironblack_palette[val])

print(f"Dumping to {outfile}")
a = np.zeros((120, 160, 3), np.uint8)
for r in range(0, 120):
    for c in range(0, 160):
        a[r, c] = transformed[(r * 160) + c]

data = im.fromarray(a, "RGB")
data.save(outfile)

camera.shutdown()
import base64
from PIL import Image as im
import numpy as np
import argparse
from tcam import TCam
import sys
from ironblack import ironblack_palette 
from rainbow import rainbow_palette 
import cv2
import time
import threading
import queue


def writer_thread_func(q, writer):
    """Continuously pull frames from the queue and write them to the video."""
    while True:
        frame = q.get()
        if frame is None:  # Sentinel value to signal the end of processing
            q.task_done()
            break
        writer.write(frame)
        q.task_done()
    print("Writer thread has exited.")

camera = TCam()
res = camera.connect("192.168.4.1")
print(f"success with the response : {res}")


fourcc = cv2.VideoWriter_fourcc(*'mp4v')
video_out = cv2.VideoWriter("output1.mp4", fourcc, 8.0, (640, 480))

outfile = "hello12.png"
frame_queue = queue.Queue(maxsize=100)

st = time.time()
rsp = camera.start_stream()

writer_thread = threading.Thread(target=writer_thread_func, args=(frame_queue, video_out))
writer_thread.start()



count = 0

while True:
    if camera.frameQueue.empty():
        continue
    img = camera.get_frame()
    dimg = base64.b64decode(img["radiometric"])
    print(img)
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
            transformed.append(rainbow_palette[255])
        else:
            transformed.append(rainbow_palette[val])

    print(f"Dumping to {outfile}")
    a = np.zeros((120, 160, 3), np.uint8)
    for r in range(0, 120):
        for c in range(0, 160):
            a[r, c] = transformed[(r * 160) + c]
    print(type(a))
    img = cv2.resize(a,(640,480))
    img = cv2.cvtColor(img,cv2.COLOR_BGR2RGB)
    
    frame_queue.put(img)

    et = time.time()
    count+=1
    print(f'FPS is : {count/(et-st)}')
    cv2.imshow("image",img)
    if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    data = im.fromarray(a, "RGB")
    # data.save(outfile)
    
frame_queue.put(None)
writer_thread.join()
cv2.destroyAllWindows()
rsp = camera.stop_stream()
camera.shutdown()
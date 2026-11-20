"""Build an underlapping interior from an actual photographed alpha channel.

The crossing surface keeps ownership of its own alpha. The inset fills the hole
and extends underneath opaque material. Reject a hole open to the image border.
"""
from pathlib import Path
import sys
import numpy as np
try:
    import cv2 as cv
except ImportError as error:
    import os
    fallback = os.environ.get('WATCH_AND_DO_OPENCV_PATH')
    if not fallback:
        raise ImportError("Install opencv-python-headless in the current Python environment.") from error
    sys.path.insert(0, fallback)
    import cv2 as cv

def interior_matte(alpha, seed, padding=3):
    x,y=np.rint(seed).astype(int)
    if not (0<=x<alpha.shape[1] and 0<=y<alpha.shape[0]):
        raise ValueError("Opening seed is outside the source.")
    count,labels,stats,_=cv.connectedComponentsWithStats(np.uint8(alpha<239))
    chosen=int(labels[y,x])
    if not chosen:
        raise ValueError("Opening seed landed on the photographed surface.")
    l,t,w,h,area=stats[chosen]
    if min(l,t)<1 or l+w>=alpha.shape[1] or t+h>=alpha.shape[0] or area<16:
        raise ValueError("Opening connects to an image boundary or is too small.")
    core=np.uint8(labels==chosen)*255
    width=2*padding+1
    support=cv.dilate(core,cv.getStructuringElement(cv.MORPH_ELLIPSE,(width,width)))
    support[(core==0)&(alpha<239)]=0
    mask=cv.GaussianBlur(support,(3,3),.48)
    mask[core!=0]=255
    return mask,core

#!/bin/bash
# Download all product bundles from a url file created by "lsdownloader search"
# and append them to a FORCE queue file
docker run -it --rm \
    -v $(pwd):$(pwd) \
    vudongpham/lsdownloader lsdownloader download \
    -w 4 -q $(pwd)/level1/queue.txt \
    $(pwd)/level1/urls_landsat_OLI_20250101T120000.txt \
    $(pwd)/level1

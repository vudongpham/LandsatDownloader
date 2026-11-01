#!/bin/bash
# Search Landsat 8/9 scenes over Berlin (2018-2020, Oct/Nov, max. 70% cloud cover) and only print a summary
docker run -it --rm \
    -v $(pwd):$(pwd) \
    vudongpham/lsdownloader lsdownloader search \
    -s OLI -d 20180101,20201231 -m 10,11 -c 0,70 \
    --secret $(pwd)/secret.txt \
    --no-action \
    $(pwd)/tests/data/berlin_bbox.gpkg \
    $(pwd)/level1

# Same search, but write the download links to a text file in the output directory
docker run -it --rm \
    -v $(pwd):$(pwd) \
    vudongpham/lsdownloader lsdownloader search \
    -s OLI -d 20180101,20201231 -m 10,11 -c 0,70 \
    --secret $(pwd)/secret.txt \
    $(pwd)/tests/data/berlin_bbox.gpkg \
    $(pwd)/level1

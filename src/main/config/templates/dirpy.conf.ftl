[global]

# Location to drop our process ID file to
# default: /var/run/dirpy/dirpy.pid
pidFile=/redfin/dirpy/run/dirpy.pid

# Log file
# default: /var/log/dirpy.log
logFile=/redfin/dirpy/logs/dirpy.log

# Root directory to use for disk-based image resizing
# default: /var/www/html
httpRoot=/data/htdocs

# Maximum pixel size of uncompressed image.  Useful for
# preventing decompression bomb attacks
# default: 90000000 (90 megapixel ~ 256 Mb 24 bit image)
maxPixels=90000000

# Default quality for lossy images, in percent
# default: 95
defQuality=93

# Minimum image size (in pixels) to allow adjustments to image quality
# default: 0
minRecompressPixels=307200

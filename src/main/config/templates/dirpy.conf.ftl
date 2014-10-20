[global]

# Location to drop our process ID file to
# default: /var/run/dirpy/dirpy.pid
pidFile=/redfin/dirpy/run/dirpy.pid

# Log file
# default: /var/log/dirpy.log
logFile=/redfin/dirpy/logs/dirpy.log

# Address to listen for requests on
# default: 0.0.0.0
bindAddr=0.0.0.0

# Port to listen for requests on
# default: 3000
bindPort=3000

# Number of worker threads to launch on program start
# default: 2 x # of cores in system 
<#if environment == "dev" || environment == "test" || environment == "trunk" || environment == "training">
# Any place where we are doing image proxying, we want a larger
# pool of worker threads, since we spend a lot of time sending
# requested out to our CDN
numWorkers=16
<#else>
#numWorkers=
</#if>

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
minDegradePixels=307200

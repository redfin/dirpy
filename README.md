Dirpy - A dynamic image modification tool 
=============================================================================


Dirpy is a Python daemon that can be used anywhere that a developer (or a user) 
requests an image of arbitrary width and/or height.  This can be useful in 
having responsive pages adapt to different viewport sizes (i.e. to the display
sizes of newly released mobile devices), as well as in allowing for rapid 
development of new graphic elements.  

By doing so, it can replace all images that are statically derived from a 
single source image (e.g. thumbnail photos).  When combined with a user-facing 
proxying webserver, this can greatly ease the load on both developers and 
system administrators by reducing the number of derivative images that need 
to be manually generated, as well as reducing the disk space required to 
store them.

A few of Dirpy's more interesting capabilities include:

  * Modifying a source image on the fly by applying one or more modification 
    commands, including:
    - Resizing/shrinking/enlarging with multiple different size/aspect controls
    - Padding images, with support for transparency 
    - Cropping images, with intelligent border detection
    - Image transposition (i.e. rotation, horizontal & vertical flipping)
  * Seamless conversion between different input & output image formats
  * Loading source images from disk, remote HTTP proxy, and user POST data
  * Saving output images to disk (useful when acting as a LRU image cache)
  * JPEG ICC profile support
  * Running in a standalone configuration or via UWSGI
  * Ability to report statistics to a StatsD daemon
  * Caching of results in a redis backend or redis cluster
  
A full list of Dirpy's commands and their options is available in the 
[Dirpy API Guide](https://github.com/redfin/dirpy/blob/master/docs/api.md).

## Requirements

Dirpy requires a semi-recent version of Python (at least Python 2.6 or 
greater), and supports Python 3.

It also requires the PIL library, as provided by the 
[Pillow fork](https://python-pillow.org/).  Before Pillow is compiled and 
installed, you should ensure that the host machine has both the standard 
and development packages of the image formats that you want to support 
installed, i.e.:

 - JPG library & development files (called libjpeg-turbo in RedHat/Centos)
 - PNG library & development files (called libpng in RedHat/Centos)
 - GIF library & development files (called giflib in RedHat/Centos)

All libraries to be used by Pillow must be installed prior to Pillow itself, 
as PIL compiles against and links to these libraries as part of its 
installation process.  For a full list of the image files that Pillow (and
subsequently Dirpy) supports, see [here](
http://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html).


## Installation

Since Dirpy is available as a PyPI module, if you have 
[pip](https://pip.pypa.io/en/stable/installing/) available, installation 
should be as simple as:

    pip install dirpy

This should install Dirpy and all of its required Python modules.  If you 
_must_ have the absolute latest and greatest, you can install directly 
from this repo:

    pip install https://github.com/redfin/dirpy/zipball/master


## Configuration

Dirpy's configuration file is fairly succint; you can find a documented
configuration file [here](
https://github.com/redfin/dirpy/blob/master/conf/dirpy.conf).


## Running

Dirpy can be run either as a standalone daemon, or as a uWSGI vassal (which
is recommended; see [here](http://uwsgi-docs.readthedocs.io) for more info).

When running under uWSGI, you can use the .ini in the 
[extras](https://github.com/redfin/dirpy/tree/master/extras) directory to 
launch Dirpy.  Otherwise, consider running Dirpy as a daemon via systemd 
(there's also a file in the extras directory for this) or sysV init.

When run from the command-line, Dirpy supports the following options:

  -h, --help            show this help message and exit
  -c CONFIG_FILE, --config-file CONFIG_FILE
                        Path to the Dirpy config file
  -d, --debug           Emit debug output
  -f, --foreground      Don't daemonize; run program in the foreground


## Usage

### Direct Dirpy Access

When accessing Dirpy directly (i.e. not through a web proxy), a remote
client can exercise the full power of Dirpy (which can be a blessing and 
a curse, as a savvy and malicious remote user could use it to wreak havoc).

Below are some example Dirpy URLs, along with explanations as to how they
would cause Dirpy to behave:

  https://127.0.0.1:3000/path/to/my/file.jpg?resize=300x200,shrink

This url will use the file "/path/to/my/file.jpg" as the source file.  The 
file should be located on the local machine inside the Dirpy HTTP root, 
which defaults to the "/var/www/html", so the fully qualified path (assuming 
a default config) would be "/var/www/html/path/to/my/file.jpg".  The file 
will be resized to a width of 300 pixels and a height of 200 pixels, 
preserving aspect ratio, but not enforcing a strict adherence to the 
requested image size (due to the lack of distort, pad or crop options).  So 
if "file.jpg" in this example was a 1000x1000 image, it would be resized to 
200x200, instead of 300x200.  


  https://127.0.0.1:3000/this/photo.jpg?resize=200x,grow&save=fmt:png

This url will use a source file whose fully qualified path (as above) would be 
"/var/www/html/this/photo.jpg", and which will be enlarged to a width of 300 
pixels with an aspect-ratio-scaled height.  So a 150x100 pixel source file 
would be resized to 300x200.  However, since this url specifies the grow 
option, source files with widths greater than or equal to 300 pixels will be 
passed through un-resized (although options such as quality and output format 
will still be obeyed).  The resulting image will be returned as a PNG.

  https://127.0.0.1:3000/a/b.jpg?resize=200x400,fill&crop&save=fmt:jpg,optimize,qual:93

This url will use the photo.jpg source file, resize it to 200x400, filling 
(with overlap) the bounding box.  It will then crop the image to 200x400 
(since the crop command will inherit the dimensions from the previous resize 
command) and then output the image as an optimize JPEG with a compression 
quality of 93%.  So, for a 1000x1000 source image, it would first be resized 
to 400x400 (aspect ratio preserved, filling bounding box) and then 
center-cropped to 200x400.

  https://127.0.0.1:3000/this/photo.jpg?crop=border,symmetric&resize=150%

Remove any border surrounding the photo.jpg source file, and then increase 
its size by 50%.

  https://127.0.0.1:3000/?load=post&resize=200x&save=todisk:myfile.jpg,noshow

Load an image from POST (thus no on-disk path is required), resize to 200 
pixels wide, save it to <todisk_root>/myfilename.jpg, and send no image
data back to the requestor. 

### Proxying through a web server

If you are exposing Dirpy's functionality to the greater internet, it is 
*strongly* recommended that you meter user's access to Dirpy via a proxying
webserver.  This is the use case that Dirpy was originally designed for, and 
will prevent remote users from performing any sort of mischief (which will 
most certainly happen if a proxying web server isn't used).

An example of using Nginx to proxy a user request to Dirpy:

    location ~ ^/thumbnail/(.+\.jpg)$
    {
        add_header Cache-Control "public";
        proxy_pass http://127.0.0.1:3000/src_photo/$1?resize=64x64,fill&crop;
    }

This will cause any request for an incoming url that matches `/thumbnail/*.jpg`
to be proxied to a backend Dirpy server (which you've restricted access to
via a local firewall or other means, right?), which will then generate a
64x64 thumbnail using the corresponding file located in 
`<http_root>/src_photo`.


## Performance tweaks

Dirpy can scale linearly with the number of processors on the host machine,
and CPU is by far its most important resource (faster/more CPUs = more
Dirpy requests/second).  Play around with the number of configured Dirpy
workers until you find the happy medium between Dirpy requests/second and
server responsiveness).

Also, considering using the [Pillow-SIMD](
https://github.com/uploadcare/pillow-simd) fork, as it offers some impressive
speed benefits over the standard Pillow module (especially if you have a
processor that supports AVX2 extensions).  To use Pillow-SIMD, install
Pillow-SIMD first, and then install Dirpy with no dependencies:

    pip install Pillow-SIMD
    pip install --no-deps dirpy

If you have already installed Dirpy, and wish to switch to Pillow-SIMD, just
uninstall Pillow and install Pillow-SIMD in its place:

    pip uninstall Pillow
    pip install Pillow-SIMD

Dirpy also supports caching results in a redis backend or redis cluster via 
the `redis` Python module, which you will need to install prior to being 
able to use this function:

    pip install redis

Enabling redis support in Dirpy is trivial; see the config for details.
Note, however, that POST requests won't be served from (or written to) the
redis server.

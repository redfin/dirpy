# Dirpy

Dirpy can be used anywhere that a developer (or a user) requests an image of arbitrary width and/or height.  This can be useful in having responsive pages adapt to different viewport sizes (i.e. to the display sizes of newly released mobile devices), as well as in allowing for rapid development of new graphic elements.  In doing so, it can replace all images that are statically derived from a single source image (e.g. thumbnail photos).


## Usage

Example Dirpy URLs

https://127.0.0.1:3000/path/to/my/file.jpg?resize=300x200,shrink

This url will use the file "/path/to/my/file.jpg" as the source file.  The file should be located on the local machine inside the Dirpy HTTP root, which defaults to the "/var/www/html", so the fully qualified path (assuming a default config) would be "/var/www/html/path/to/my/file.jpg".  The file will be resized to a width of 300 pixels and a height of 200 pixels, preserving aspect ratio, but not enforcing a strict adherence to the requested image size (due to the lack of distort, pad or crop options).  So if "file.jpg" in this example was a 1000x1000 image, it would be resized to 200x200, instead of 300x200.  


https://127.0.0.1:3000/this/photo.jpg?resize=200x,grow&save=fmt:png

This url will use a source file whose fully qualified path (as above) would be "/var/www/html/this/photo.jpg", and which will be enlarged to a width of 300 pixels with an aspect-ratio-scaled height.  So a 150x100 pixel source file would be resized to 300x200.  However, since this url specifies the grow option, source files with widths greater than or equal to 300 pixels will be passed through un-resized (although options such as quality and output format will still be obeyed).  The resulting image will be returned as a PNG.

https://127.0.0.1:3000/this/photo.jpg?resize=200x400,fill&crop&save=fmt:jpg,optimize,qual:93

This url will use the photo.jpg source file, resize it to 200x400, filling (with overlap) the
bounding box.  It will then crop the image to 200x400 (since the crop command will
inherit the dimensions from the previous resize command) and then output the
image as an optimize JPEG with a compression quality of 93%.  So, for a 1000x1000
source image, it would first be resized to 400x400 (aspect ratio preserved, filling
bounding box) and then center-cropped to 200x400.

https://127.0.0.1:3000/this/photo.jpg?crop=border,symmetric&resize=150%

Remove any border surrounding the photo.jpg source file, and then increase its size by 50%.


## Requirements

Dirpy requires a semi-recent version of Python (at least Python 2.6 or greater), but is untested with Python 3 (it will likely need to be run through the 2to3 script, and have several other modifications made to it, before it will run in Python 3).

It requires the PIL library, as provided by the Pillow Fork.  Before PIL is compiled and installed, you should ensure that the host machine has both the standard and development packages of the following libraries installed:
	JPG library 	(called libjpeg-turbo in RedHat/Centos)
	PNG library 	(called libpng in RedHat/Centos)
	GIF library 	(called giflib in RedHat/Centos)

You may also want to consider installing the libraries for other less-frequently used, but still desirable formats (such as WebP or TIFF).  All libraries to be used by PIL must be installed before PIL itself, as PIL compiles against and links to these libraries as part of its installation process.


## Adding a new image type

1. Decide upon the transformation parameters that will need to be applied to this new image type.  E.g:  Will it need to be resized to a specific X dimension but have an unbounded Y dimension (or vice versa)?  Do you want to refrain from making small images larger (using the "shrink" command)?  Assuming you want to preserve aspect ratios (usually a given), do you want to crop image data that lies outside the bounding box?

1. Construct the query string that will perform the actual image resizing, referring to the API section as necessary.  Look at the Example Dirpy URLs section for some examples on query string formats.

1. Open the image server nginx config template, and add a location stanza that specifies that path that defines your new image type, and the proxy URL that you created in step #2.  For example:

        location ~ ^/photo/(\d+)/abcphoto/([^/]+)/genAbc\.([^/]+)$
        {
            add_header Cache-Control "public";
            proxy_pass http://127.0.0.1:3000/photo/$1/bigphoto/$2/$3?resize=shrink,320x230,fill&crop;
        }

 Consider using a three letter code (such as 'abc', in the example above) to identify your image, as this is the format used by current image types.  You shouldn't need to change any of the portion of the "location" line other than this three letter code.

 Note that you will want to use the "proxy" and "fallback" options in the save command (i.e. "&save=proxy:http://media.cdn-redfin.com,fallback") in your query string while creating image sizes in the test environment, since the test image servers do not host all of the images used by the main site and thus we must proxy from the Redfin images CDN.

1. Deploy the altered nginx config to the testing images servers and to restart the nginx daemons on them.

1. Test your new image size.  You can do hitting a URL at the testphotos server, e.g.:
http://example.com/photo/1/abcphoto/910/genAbc.701910_1_1.jpg

1. Assuming that your photo is resizing the way that you'd like, commit your new location block from step 4 to the production nginx config.  Make ABSOLUTELY SURE to remove the "proxy" and "fallback" options in the query string, as this could cause an endless recursive query in Dirpy that would very quickly consume all of the available Dirpy connections).

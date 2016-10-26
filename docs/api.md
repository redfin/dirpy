Dirpy API
=============================================================================

The Dirpy API is completely based on the request strings passed to it.  The 
request string consists of two parts: the path and the query string.  Request 
strings are formatted as: 

http[s]://server.address[:port]/<path>?<query string>

The query string should consist of field-value pairs (separated by ampersands)
where each field corresponds with a Dirpy command (i.e. loading an image, 
resizing, cropping, etc).  Field values should be comma-delimited strings of 
options and their values (which are colon-delimited).  So a full example 
request string would appear like.  As some options are boolean, option 
values are not always required.  Additionally, some commands can be run with 
no options specified (e.g. when running a crop command after a bounded resize) 
and thus the option strings are likewise not always required.  An example of 
the URL format used by Dirpy is:

  https://127.0.0.1:3000/a/b.jpg?cmd1=opt1:val1,opt2&cmd2=opt3,opt4=val4&cmd3

The path in this case should point to the source file that is being modified 
(either on the local disk of the machine hosting the Dirpy daemon, or on a 
remote server when proxying).  Here we can see that commands "cmd1", "cmd2" 
and "cmd3" are being run.  "cmd1" has two options specified: "opt1" has a 
value of "val1", and "opt2" has a value of "true", as it has no value defined.

The most important thing to note when constructing Dirpy URLs is that Dirpy 
commands, with the exception of the "load" and "save" commands, are 
positional.  That is, "resize&crop" is not the same as "crop&resize".  
The former will resize and then crop, while the latter will crop and then 
resize, likely resulting in completely different images sized.

## Dirpy commands:

### load        

Loads an image from local disk or remote web server.  This command is run 
prior to any others, using the <path> portion of the URL passed to Dirpy and 
appending it to the HTTP root directory specified in the Dirpy config file 
(usually "/var/www/html").  This command is run regardless of whether or not 
it is defined in the query string; it only needs to be defined in the query 
string when specifying non-default options (e.g. when proxying).

Options:    

  * proxy:<proxy URL>   
  Instead of loading an image from local disk, load it from a remote web 
  server using the specified path.  So a Dirpy URL like: 
  "http://dirpy:3000/foo/bar.jpg?load=proxy:https://boo.com/baz" will attempt
  to load the source image from "https://boo.com/baz/foo/bar.jpg".

  * fallback  
  A boolean option indicating that proxying should only be attempted if the 
  file is not available on the local disk.

  * post
  Instead of loading from disk (or via proxy) the image is loaded directly 
  from data supplied via HTTP POST.  This data must be encoded using the 
  multi-part/form-data content type, specified in RFC 2388.  The image data  
  in question should be sent using a form-field element named "file".  This 
  option requires the "allow_post" config value be set to "true".
    
### resize
    
Resizes an image via either a fixed height and/or width, or a percentage.

Options:
    
* `[width]x[height]`  
Height and/or width, in pixels, to resize image to.  It is permissible to
define only one of the two dimensions, in which case the undefined
dimension is calculated using the ratio of the defined dimension to the
source image original dimensions.  Dimensions defined by height and/or
width will be inherited by subsequent commands, unless specifically 
overridden (i.e. a `crop` command following a `resize` command will 
inherit the resize command dimensions).

* `<percentage>%`  
Increase or decrease the image size by the specified percentage.  Mutually
exclusive with width/height-based resizing, as well as the `unlock`, 
`fill`, `shrink` and `enlarge` options.

* `unlock`  
Remove aspect ratio locking. This option requires that both width and
height values to be defined, and results in an image that completely
fills the requested dimensions.  If the requested aspect ratio is not
identical to the original image aspect ratio, the image will be distorted.
Mutually exclusive with the `fill` and `percentage` options.

* `fill`  
Invert the resize boundary logic.  This option requires that both width 
and height values to be defined, and causes the smaller of the two 
original dimensions to be the limiting dimension (instead of the larger
dimension, which is the default).  This means that the larger of the two
resulting dimensions will have a value greater than the requested
dimension, causing the resized image to exceed the size of the requested
bounding box.  This is useful when combined with a subsequent crop
command, to make an image exactly match the requested image dimensions
while still honoring the original image aspect ratio. Mutually exclusive
with the `unlock` and `percentage` options.

* `shrink`  
Only decrease the image size when resizing.  If the original image lies
entirely inside the boundary delineated by the user-requested height and
width, no resize is performed.  Mutually exclusive with `pct` and `grow`
options.

* `grow`  
Only increase the image size when resizing.  If the original image lies
partially or entirely outside the boundary delineated by the
user-requested height and width, no resize is performed.  Mutually
exclusive with `pct` and `shrink` options.

* landscape  
Apply `fill` logic if the original image width is greater than its height.
Otherwise resize as normal.

* `portrait`  
Apply `fill` logic if the original image height is greater than its width.
Otherwise resize as normal.

* `filter:<filter type>`  
Set the filter to be used by the resize operation.  Filters will affect 
resulting image quality, as well as resize speed.  Filters, in general
order of increasing quality and decreasing speed, are:
    - nearest (use nearest neighbour)
    - bilinear (bilinear interpolation)
    - bicubic (bicubic interpolation)
    - antialias (3-lobed lanczos downsampling, the default)
    
### crop

Crop the image to the specified dimensions or coordinates.

Options:

* `border[:<fuzziness>]`  
Automatic border detection and cropping.  If the source image has a 
border with a near-constant color, the border will be removed. Border 
detection sensitivity is adjustable via the optional fuzziness parameter,
which should be an integer between 0 (least sensitive) and 255 (most
sensitive). Mutually exclusive with the dimension and coordinate-based
cropping methods.

* `symmetric`  
Forces automatic border cropping (provided by the border option) to
remove equal amounts from the left and right sides, as well as the top
and bottom.  This ensures that the original image remains centered.

* `[width]x[height]`  
Similar to the dimension option used by the resize command.  Use the 
gravity option for a non-centered crop. Mutually exclusive with a 
coordinate-based crop and `border` option.

* `<left X>x<top Y>x<right X>x<bottom Y>`  
A coordinate-based crop, specifying the upper-left and lower-right
coordinates that define the bounding box to crop the image to.  
All four values must be defined.  Mutually exclusive with the 
dimension-based crop and `gravity` and `border` options.

* `gravity:<gravity type>`  
The gravity to use when performing a dimension-based crop.  Gravity types
correspond with abbreviated compass directions (with "c"enter being the
default): "n", "ne", "e", "se", "s", "sw", "w", "nw", and "c".

### pad  

Pad the image to the specified dimensions.

Options:

* `[width]x[height]`  
Similar to the two-dimension option used by the resize command.   Pad the
image to these dimensions.

* `gravity:<gravity type>`  
Similar to the gravity used by the crop command; place the original image
inside the padded boundary based on the gravity specified here ("c"enter
being the default).

* `bg:<color>`  
The background color to use when filling the padded area.  This can either
be a html color name (e.g. "cornflower blue") or a 3 or 6 digit RGB color
code, without the hash sign (e.g. "659CEF").

* `trans:<transparency %>`  
The level of transparency to set the background to (only supported in
RGBA mode; mode will automatically be set to RGBA if this option is
specified).  Note that partial (i.e. alpha channel) transparency is
currently only supported in PNG and WEBP formats. Setting a non-zero
transparency value for a GIF will make the background color fully 
transparent.

* `transpose:<option>`  
Flip or rotate the image.  All transpose options are mutually exclusive
with one-another. Options are:
    - flipvert : Flip the image around the vertical axis (left-to-right)
    - fliphorz : Flip the image around the horizontal axis (top-to-bottom)
    - rotate90, rotate180, rotate270 : Rotate clockwise

### save

Return the modified image to the end-user.

Options:

* `fmt:<format type>`  
Specifies the output format to be used by the resized image (as well as 
sets the Content-Type header MIME value).  Note that the format must be
one of the output formats supported by PIL and must have been compiled
into the PIL Python module at install-time.

* `qual:<value>`  
Specified as an integer from 1 to 100, sets the default image quality of
the output format (which only affects lossy codecs such as jpeg and WebP).

* `progressive`  
Generate a progressive image (assuming a JPEG or PNG output type). 

* `optimize`  
Forces a second resizing pass.  This will often generate higher quality
images with smaller image sizes, at the cost of a slightly slower resize
operation.

* `todisk:<path>`  
Writes the resulting image to local disk on the Dirpy server.  Useful if
you wish to implement a Dirpy cache using a try_files directive in Nginx
(so after an image is resized once, Nginx will serve the result from disk
after that).  Requires the `allow_todisk` config option to be set to true
and the `todisk_root` config option to be set to an existing on-disk
directory.  Creating sub-directories under this root directory and
overwriting existing files require the `allow_mkdir` and `allow_overwrite`
config options to be set to true, respectively.

* `noshow`  
Do not return the actual image data resulting from the requested Dirpy 
operations, instead return an empty response.  The HTTP status code 
returned will still be relevant, however: 200 for a successful resize, 4xx
for a user error, 5xx for an internal server error.  Useful when paired
with the todisk option to front-load data for later consumption. Note
that this option will cause Dirpy to return a 204 (No Content) HTTP
response on a successful resize, instead of the typical 200.

### status

If the status command is specified (without any arguments), then all other
commands are ignored and the server immediately returns a "204: no content"
reponse.  This is useful for enabling monitoring scripts and the like
to programatically determine if the Dirpy daemon is running, by querying
an URL like:

  http://127.0.0.1:3000?status


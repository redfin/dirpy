__version__ = "1.3.0"

import argparse
import cgi
import collections
import datetime
import errno
import hashlib
import io
import json
import logging
import multiprocessing
import os
import re
import signal
import socket
import sys
import time
import traceback
import urllib

# Python2/3 module disambiguation
if sys.version[0] == '3':
    import configparser
    import http.server as http_server
    import urllib.request as urllib2
    import urllib.parse as urlparse
    import pickle
else:
    import ConfigParser as configparser
    import BaseHTTPServer as http_server
    import urllib2
    import urlparse

    # Load pickle for cache serialization
    try:
        import cPickle as pickle
    except ImportError:
        import pickle

# Gracefully exit if PIL is missing
try:
    from PIL import Image, ImageFile, ImageColor, ImageChops, ImageDraw
except:
    print("Missing the PIL module; consult https://github.com/redfin/dirpy " +
        "for instructions on how to install PIL.")
    sys.exit(1)

# Workaround for truncated images
ImageFile.LOAD_TRUNCATED_IMAGES = True

# The dirpy image class.  Defines the various operations that can be performed
# on images loaded by dirpy
class DirpyImage: ############################################################

    def __init__(self, http_root):
        self.logger         = logging.getLogger("dirpy")
        self.local_file     = None
        self.file_path      = None
        self.req_dims       = [None, None]
        self.num_dims       = 0
        self.gravity        = None
        self.im_in          = None
        self.in_fmt         = None
        self.in_size        = 0
        self.out_buf        = io.BytesIO()
        self.out_size       = 0
        self.out_x          = 0
        self.out_y          = 0
        self.in_x           = 0
        self.in_y           = 0
        self.out_fmt        = None
        self.save_opts      = {}
        self.trans          = None
        self.modified       = False
        self.http_root      = http_root
        self.meta_data      = collections.defaultdict(dict)
        self.http_code      = 200
        self.http_msg       = "OK"

        self.init_time      = time.time()

    # Run a command, provided that it is value
    def run(self, cmd, opts):
        if cmd.startswith("_"):
            raise DirpyUserError("Internal method not run()-able: %s" % cmd)
        try:
            method = getattr(self, cmd)
        except AttributeError:
            raise DirpyUserError("Unknown command: %s" % cmd)

        method(opts)
        

    # Load an image file, either from disk or a local HTTP(S) server
    def load(self, opts, rel_file, req_post_data): ###########################

        # Measure the time it takes to load our file
        load_start = time.time()

        # A file-like object to store the result of our BytesIO
        # output (in the event of a proxied result) or the contents
        # of the local file read from disk
        file_obj = None

        # Normalize our path (and prevent directory traversal)
        self.local_file = os.path.normpath(cfg.http_root +
            os.path.normpath("/" + rel_file))

        # Parse our options
        proxy       = opts["proxy"] if "proxy" in opts else None
        fallback    = "fallback" in opts
        from_post   = "post" in opts

        # Try to open our file
        try:
            # Load a file via POST data if the stars are aligned
            if from_post and req_post_data:
                if cfg.allow_post:
                    self.logger.debug("Loading post data: %s" % str(opts))
                    file_obj = req_post_data
                    self.file_path = "POST_file"
                    self.in_size = len(file_obj.getvalue())
                else:
                    raise DirpyUserError("POST prohibited.")


            # Proxy a file from a remote server, if requested
            elif proxy and not (fallback and os.path.isfile(self.local_file)):
                self.file_path = proxy + rel_file
                self.logger.debug("Loading image %s: %s" % 
                    (self.file_path, str(opts)))
                proxy_req = urllib2.Request(self.file_path,
                    headers={"User-Agent": "Dirpy/" + __version__})
                proxy_res = urllib2.urlopen(proxy_req)
                file_obj = io.BytesIO(proxy_res.read())
                self.in_size = len(file_obj.getvalue())

            # Otherwise read it locally
            else:
                self.file_path = self.local_file
                self.logger.debug("Loading image %s: %s" % 
                    (self.file_path, str(opts)))
                file_obj = open(self.file_path, "rb")
                self.in_size = os.fstat(file_obj.fileno()).st_size

            self.logger.debug("Serving file: %s" % self.file_path)
        except Exception as e:
            err_code = e.code if hasattr(e, "code") else 500
            raise DirpyFatalError("Error reading file: %s" % e, err_code)


        # Read in the image from the file object
        try:
            self.im_in = Image.open(file_obj)

            # Record our input format and dimensions
            self.in_fmt = self.im_in.format.lower()
            self.out_x, self.out_y = self.im_in.size
            self.in_x, self.in_y = self.im_in.size

            self.meta_data["g"]["in_width"]      = self.in_x
            self.meta_data["g"]["in_height"]     = self.in_y
            self.meta_data["g"]["in_bytes"]      = self.in_size
            self.meta_data["ms"]["load_time"]    = time.time() - load_start

            self.meta_data["c"]["in_fmt_" + self.in_fmt] = 1

            self.meta_data["c"]["total"]         = 1
            self.meta_data["c"]["cache_hit"]     = 0

            # Guard against decompression bombs
            if cfg.max_pixels and self.out_x * self.out_y > cfg.max_pixels:
                raise DirpyUserError("Image exceeds maximum pixel limit")

        except Exception as e:
            raise DirpyUserError("Error opening image: %s" % e, 400)


    # Resize an image
    def resize(self, opts): ##################################################

        self.logger.debug(
            "Resizing image %s: %s" % (self.file_path, str(opts)))

        # Measure time spent resizing
        resize_start = time.time()

        # Fetch our percentage resize value (if any)
        try:
            pct = int(opts["pct"]) if "pct" in opts else None
        except ValueError:
            raise DirpyUserError("Percent size must be an integer: %s" % 
                opts["pct"])

        # Get our dimensions (if specified)
        dim_set = self._get_req_dims(opts)
        if len(self.req_dims) != 2 and not pct:
            raise DirpyUserError("Resize requires either 1 or 2 dimensions")
        req_x, req_y = self.req_dims

        # Set our boolean operators
        unlock      = "unlock" in opts          # remove aspect ratio locking
        fill        = "fill" in opts            # use smaller dim. as limit
        shrink      = "shrink" in opts          # only shrink images
        grow        = "grow" in opts            # only grow images
        landscape   = "landscape" in opts       # resize using landscape mode
        portrait    = "portrait" in opts        # resize using portrait mode

        # Determine if we have any missing or conflicting options
        if not (req_x or req_y or pct):
            raise DirpyUserError("Need height and/or width or pct for resize")
        if dim_set and pct:
            raise DirpyUserError("Height/width & pct are mutually exclusive")
        if unlock + fill + landscape + portrait > 1:
            raise DirpyUserError("Unlock/fill/landscape/portrait " 
                "are mutually exclusive")
        if (unlock or fill or landscape) and not (req_x and req_y):
            raise dirpyerror("Unlock/fill/landscape/portrait "
                "need both width and height")
        if shrink and grow:
            raise DirpyUserError("Shrink and grow are mutually exclusive")
        if pct and (unlock or fill):
            raise DirpyUserError("Unlock/fill/landscape/portrait "
                "not used for pct resize")
        if pct and (shrink or grow):
            raise DirpyUserError("Shrink/grow not used for pct-based resize")

        # Set our resampling filter
        filter_name = opts["filter"] if "filter" in opts else None
        if filter_name == "nearest":
            filter_type = Image.NEAREST
        elif filter_name == "bilinear":
            filter_type = Image.BILINEAR
        elif filter_name == "bicubic":
            filter_type = Image.BICUBIC
        else:
            filter_name = "antialias";
            filter_type = Image.ANTIALIAS

        # Calculate height and width resize rations based on original image
        # dimensions, user-requested dimensions, and aspect ratio options
        new_x = new_y = None
        if pct:
            resize_ratio = float(pct)/100
        elif unlock:
            resize_ratio = min(float(req_x)/self.out_x, 
                float(req_y)/self.out_y)
            new_x, new_y = req_x, req_y
        elif landscape:
            if self.out_x > self.out_y:
                resize_ratio = max(float(req_x)/self.out_x,
                    float(req_y)/self.out_y)
            else:
                resize_ratio = min(float(req_x)/self.out_x,
                    float(req_y)/self.out_y)
        elif portrait:
            if self.out_x < self.out_y:
                resize_ratio = max(float(req_x)/self.out_x,
                    float(req_y)/self.out_y)
            else:
                resize_ratio = min(float(req_x)/self.out_x,
                    float(req_y)/self.out_y)
        else:
            if not req_y:
                resize_ratio = float(req_x)/self.out_x
            elif not req_x:
                resize_ratio = float(req_y)/self.out_y
            elif fill:
                resize_ratio = max(float(req_x)/self.out_x, 
                    float(req_y)/self.out_y)
            else:
                resize_ratio = min(float(req_x)/self.out_x, 
                    float(req_y)/self.out_y)

        # Evaluate our target dimensions to preserve aspect ratio
        if new_x is None:
            new_x = int(self.out_x * resize_ratio)
        if new_y is None:
            new_y = int(self.out_y * resize_ratio)

        self.logger.debug(
            "Resize: out_x=%s out_y=%s new_x=%s new_y=%s ratio=%s" %
            (self.out_x, self.out_y, new_x, new_y, resize_ratio))

        # Now do the actual resize
        try:
            if not shrink and resize_ratio > 1:
                self.im_in = self.im_in.resize((new_x, new_y), filter_type)
                self.modified = True
            elif not grow and resize_ratio < 1:
                self.im_in.draft(None,(new_x,new_y))
                self.im_in = self.im_in.resize((new_x, new_y), filter_type)
                self.modified = True
            self.out_x, self.out_y = self.im_in.size
        except Exception as e:
            raise DirpyFatalError("Error resizing: %s" % e)

        # Record resize time
        if "time_resize" in self.meta_data:
            self.meta_data["ms"]["time_resize"] += time.time() - resize_start
        else:
            self.meta_data["ms"]["time_resize"] = time.time() - resize_start


    # Crop an image
    def crop(self, opts): ####################################################

        self.logger.debug("Cropping image %s: %s" 
            % (self.file_path, str(opts)))

        # Make sure that we have an appropriate dimension set
        self._get_req_dims(opts)

        # Handle automatic border cropping
        if "border" in opts:

            # Allow fuziness modification
            if opts["border"] is True:
                fuzz = 100
            else:
                try:
                    fuzz = int(opts["border"])
                    if not 0 < fuzz < 255:
                        raise Exception
                except:
                    raise DirpyUserError(
                        "Crop fuzz must be an integer between 0 and 255: %s"
                        % opts["border"])

            # Do an image channel difference, and then get the bounding box
            # to determine where the border is
            bg = Image.new(self.im_in.mode, self.im_in.size, 
                self.im_in.getpixel((0,0)))
            diff = ImageChops.difference(self.im_in, bg)
            new_dims = list(ImageChops.add(diff, diff, 2.0, -fuzz).getbbox())

            # Make border cropping symmetric, if requested
            if "symmetric" in opts:
                if new_dims[0] > self.out_x - new_dims[2]:
                    new_dims[0] = self.out_x - new_dims[2]
                elif new_dims[2] < self.out_x - new_dims[0]:
                    new_dims[2] = self.out_x - new_dims[0]
                
                if new_dims[1] > self.out_y - new_dims[3]:
                    new_dims[1] = self.out_y - new_dims[3]
                elif new_dims[3] < self.out_y - new_dims[1]:
                    new_dims[3] = self.out_y - new_dims[1]
                

        # Handle gravity crop (i.e. a dimension-based crop)
        elif self.num_dims == 2:
            # Unlike coordinate-based cropping, we correct crop boundaries 
            # outside our image boundary, as we can inherit crop dimensions
            # from previous commands which may have shrank the image 
            # boundary below the specified dimensions

            if self.req_dims[0] > self.out_x:
                self.req_dims[0] = self.out_x
            if self.req_dims[1] > self.out_y:
                self.req_dims[1] = self.out_y

            # Don't bother cropping if our image is the same size as our
            # requested crop size
            if (self.req_dims[1] == self.out_y 
                    and self.req_dims[0] == self.out_x):
                return

            new_dims = self._get_new_dims(opts)

        # Handle the exact crop (i.e. a coordinate-based crop)
        elif self.num_dims == 4:

            # Sanity checks
            if "gravity" in opts:
                raise DirpyUserError("Gravity only used for dimension crops")

            if None in self.req_dims:
                raise DirpyUserError(
                    "All values required in a cordinate-based crop: %s" %
                    str(self.req_dims))

            if not (self.req_dims[0] < self.req_dims[2] and
                    self.req_dims[1] < self.req_dims[3]):
                raise DirpyUserError(
                    "Coordinates a,b,c,d should have a < c and b < d: " %
                    str(self.req_dims))

            if (self.req_dims[0] < 0 or self.req_dims[1] < 0 or
                    self.req_dims[2] > self.out_x or 
                    self.req_dims[3] > self.out_y):
                raise DirpyUserError(
                    "Crop corners must be inside source image border: %s" %
                    str(self.req_dims))

            new_dims = self.req_dims

        # Handle invalid # of crop dims
        else:
            raise DirpyUserError("Crop requires dimensions or coordinates")

        self.logger.debug("Crop: out_x=%s out_y=%s crop_box=%s, grav=%s" %
            (self.out_x, self.out_y, str(new_dims), self.gravity))

        # Now crop the image
        try:
            self.im_in = self.im_in.crop(new_dims)
            self.im_in.load()
            self.out_x, self.out_y = self.im_in.size
            self.modified = True
        except Exception as e:
            raise DirpyFatalError("Error cropping: %s" % e)


    # Pad an image
    def pad(self, opts): #####################################################

        self.logger.debug("Padding image %s: %s" 
            % (self.file_path, str(opts)))

        # Make sure that we have an appropriate dimension set
        self._get_req_dims(opts)
        if self.num_dims != 2:
            raise DirpyUserError("Pad requires no more than 2 dimensions")

        # Sanity check
        if (self.req_dims[0] < self.out_x or 
                self.req_dims[1] < self.out_y):
            raise DirpyUserError(
                "Pad area must be larger than source image: %s < [%s,%s]" %
                (str(self.req_dims), self.out_x, self.out_y))

        # Process transparency request
        if "trans" in opts:
            try:
                self.trans = int(opts["trans"]) 
                assert 0 <= self.trans <= 255
            except Exception as e:
                raise DirpyUserError("Transparency must be an integer "
                    "between 0 and 255, inclusive")

        # Determine what our background color tuple will be
        try:
            if "bg" in opts:
                req_color = opts["bg"]
            else:
                req_color = "white"

            hex_match = re.match(r"[0-9a-fA-F]{3,6}", req_color)
            if hex_match:
                req_color = "#" + req_color

            if self.trans is not None:
                pad_mode = "RGBA"
            else:
                pad_mode = self.im_in.mode

            pad_color = ImageColor.getcolor(req_color, pad_mode)

        except Exception as e:
            raise DirpyUserError("Not a valid color: %s, %s" % (req_color,e))
        
        # Get our interior dimension locations
        new_dims = self._get_new_dims(opts)

        # Create the padded image and insert our old image into it and
        # then overwrite our existing input image with the paddded one
        try:
            im_pad = Image.new(pad_mode, self.req_dims, pad_color)
            im_pad.paste(self.im_in, new_dims)

            if self.trans is not None:
                mask_dims=(
                    new_dims[0], new_dims[1], new_dims[2]-1, new_dims[3]-1)
                im_mask = Image.new('L', self.req_dims, color=self.trans)
                ImageDraw.Draw(im_mask).rectangle(mask_dims, fill=255)
                im_pad.putalpha(im_mask)

            self.im_in = im_pad
            self.out_x, self.out_y = self.im_in.size
            self.modified = True
        except Exception as e:
            raise DirpyFatalError(
                "Error padding image %s: %s" % (self.file_path,e))


    # Transpose an image
    def transpose(self, opts): ###############################################

        self.logger.debug("Transposing image %s: %s" 
            % (self.file_path, str(opts)))


        # Parse possible arguments
        num_args = 0
        if "flipvert" in opts:
            method = Image.FLIP_LEFT_RIGHT
            num_args += 1
        if "fliphorz" in opts:
            method = Image.FLIP_TOP_BOTTOM
            num_args += 1
        if "rotate90" in opts:
            method = Image.ROTATE_90
            num_args += 1
        if "rotate180" in opts:
            method = Image.ROTATE_180
            num_args += 1
        if "rotate270" in opts:
            method = Image.ROTATE_270
            num_args += 1

        if num_args != 1:
            raise DirpyUserError(
                "Transpose requires exactly one option: %s" % str(opts))

        # Now rotate
        try:
            self.im_in = self.im_in.transpose(method)
            self.out_x, self.out_y = self.im_in.size
            self.modified = True
        except Exception as e:
            raise DirpyFatalError(
                "Error transposing image %s: %s" % (self.file_path,e))


    # Write an image to a BytesIO output buffer
    def save(self, opts): ####################################################

        self.logger.debug("Saving image %s: %s" % (self.file_path, str(opts)))

        # Measure time spent saving
        save_start = time.time()

        # Handle save options
        noicc       = "noicc" in opts
        progressive = "progressive" in opts
        optimize    = "optimize" in opts
        noshow      = "noshow" in opts
        
        # Determine if we are being asked to save the result to disk locally
        # (and if we are permitted to)
        if "todisk" in opts:
            if not cfg.allow_todisk:
                raise DirpyUserError(
                    "Saving to disk forbidden: %s" % str(opts))
            if not cfg.todisk_root:
                raise DirpyUserError(
                    "Save to disk path unset: %s" % str(opts))
            todisk_path = os.path.normpath(cfg.todisk_root +
                os.path.normpath("/" + opts["todisk"]))
        else:
            todisk_path = False

        # Set and spot-check our output format
        if "fmt" in opts:
            self.out_fmt = opts["fmt"].lower()
        elif self.in_fmt:
            self.out_fmt = self.in_fmt
        else:
            self.logger.debug("Can't determine encoder; falling back to jpeg")
            self.out_fmt = "jpeg" # Fall back to jpeg

        # Fix any attempts to use the non-existant "jpg" output plugin
        if self.out_fmt == "jpg":
            self.out_fmt = "jpeg"

        # Set output quality (only affects jpeg/webp formats)
        if self.out_fmt in ("jpeg", "webp"):
            try:
                if "qual" in opts:
                    qual_val = int(opts["qual"])
                else:
                    qual_val = cfg.def_quality
            except:
                raise DirpyUserError("Quality must be an integer")

            # Make sure we got a valid quality percentage
            if not 0 < qual_val < 101:
                raise Exception("Invalid quality")

            # Dont recompress input images that are less than this size
            if self.out_x * self.out_y < cfg.min_recompress_pixels:
                self.logger.debug("Not recompressing image: %s < %s" % 
                    (self.out_x * self.out_y, 
                    cfg.min_recompress_pixels))
                qual_val=95

        else:
            qual_val = None

        # Handle pallette-style transparency
        if self.out_fmt in ("gif"):
            if self.trans is not None:
                self.save_opts["transparency"] = 0

        # Preserve our ICC profile if this is a JPEG, unless explicitly
        # requested otherwise
        icc_prof = None
        if self.in_fmt == "jpeg" and not noicc:
            icc_prof = self.im_in.info.get("icc_profile")

        # Convert pallette mode to RGB, if this is a jpeg, since JPEG 
        # doesn't support mode P
        if self.out_fmt == "jpeg" and self.im_in.mode == "P":
            self.im_in = self.im_in.convert("RGB")

        # Maintain the encoder subsampling to prevent jpeg->jpeg size bloat
        # (although this only works on un-modified images)
        if self.in_fmt == self.out_fmt == "jpeg" and not self.modified:
            self.im_in.format = "JPEG"
            qual_val = "keep"
            self.logger.debug("Preventing JPEG recompression.")

        # Now write the converted image to a buffer
        try:
            # Our output arguments.  We have to to use a kwargs pointer, as
            # the save function will sometimes interpret the presence of
            # an argument (regardless of its value) to mean a true value

            # Bump up the ImageFile.MAXBLOCK size when writing optimized or
            # progressive images to avoid a legacy PIL bug
            self.save_opts["format"] = self.out_fmt
            if progressive or optimize:
                ImageFile.MAXBLOCK =  max(
                    self.in_x * self.in_y, 
                    self.out_x * self.out_y, 2097152)
                self.logger.debug("MAXBLOCK set to: %s" % ImageFile.MAXBLOCK)
            if optimize: 
                self.save_opts["optimize"] = True
            if progressive: 
                self.save_opts["progressive"] = True
            if icc_prof is not None: 
                self.save_opts["icc_profile"] = icc_prof
            if qual_val is not None:
                self.save_opts["quality"] = qual_val

            # Save our image to the bytesIO buffer, with all of our
            # various user-defined or default config options
            # Note that any "failed to suspend" errors here are typically
            # caused by your MAXBLOCK variable being too small
            try:
                self.im_in.save(self.out_buf, **self.save_opts)
            except Exception as e:
                raise DirpyFatalError("Failed to save image: %s" % e)

            # If we are being asked to write to disk, do so
            if todisk_path:

                # Verify that the file doesn't exist on disk already and/or
                # that we are allowed to overwrite it
                if os.path.exists(todisk_path) and not cfg.allow_overwrite:
                    raise DirpyUserError("Can't overwrite %s" % todisk_path)

                # Make the subdirectory if necessary (and permitted)
                this_dir = os.path.dirname(todisk_path)
                if os.path.exists(this_dir):
                    if not os.path.isdir(this_dir):
                        raise DirpyUserError(
                            "%s exists and is not a directory" % this_dir)
                elif not cfg.allow_mkdir:
                    raise DirpyUserError(
                        "%s doesn't exist and allow_mkdir is False" 
                        % this_dir)
                else:
                    try:
                        os.makedirs(this_dir)
                    except OSError as e:
                        if (e.errno == errno.EEXIST 
                                and os.path.isdir(this_dir)):
                            pass
                        else:
                            raise DirpyFatalError(
                                "Can't mkdir %s: %s" % (this_dir, e))

                # Now write the BytesIO buffer to disk
                try:
                    self.logger.debug("Saving to disk at '%s'" % todisk_path)
                    with open(todisk_path, 'w') as out_file:
                        self.out_buf.seek(0,os.SEEK_SET)
                        out_file.write(self.out_buf.read())
                except Exception as e:
                    raise DirpyFatalError("Can't save image to disk: %s" % e)

            # Seek to the end of the buffer so we can get our content
            # size without allocating to a string (which we don't want
            # to do if this is a HEAD request).  Then seek back to the 
            # beginning so we can read the string later
            self.out_buf.seek(0,os.SEEK_END)
            self.out_size = self.out_buf.tell()
            self.out_buf.seek(0)

            # If the user has requested "noshow", we don't want to return the
            # image back to them (presumably because we have saved it to disk
            # and that is all they care about, so we don't have to waste
            # network overhead sending the image back to them)
            if noshow:
                logger.debug("Not showing %s, as requested" % self.file_path)
                self.out_buf = io.BytesIO()

            # Put together some image metadata in JSON format
            self.meta_data["g"]["out_width"]     = self.out_x
            self.meta_data["g"]["out_height"]    = self.out_y
            self.meta_data["g"]["out_bytes"]     = self.out_size
            self.meta_data["ms"]["time_save"]    = time.time() - save_start

            self.meta_data["c"]["out_fmt_" + self.out_fmt] = 1

        except DirpyFatalError:
            raise
        except DirpyUserError:
            raise
        except Exception as e:
            raise DirpyFatalError("Error converting image '%s': %s" %
                (self.file_path, e))


    # Iterate through our options keys and see if any of them match the NxN 
    # pattern for image dimensions.  Dropping one of the two image dimensions 
    # is permitted (i.e. '640x480',' '640x' & 'x480' are valid dimensions).
    def _get_req_dims(self, opts): ###########################################

        dims = []

        for o in [ n for n in opts if "x" in n]:
            try:
                o_dims = [None if x == "" else int(x) for x in o.split("x",3)]
            except ValueError:
                continue

            # Expand our final dimension array to be as large as the
            # one that we are currently inspecting
            dims += [None]*(len(o_dims)-len(dims))
            
            # Iterate over each dimension in this list and make sure that we
            # haven't set it in a previous iteration
            for i in range(0, len(dims)):
                if o_dims[i] is not None:
                    if dims[i] is not None:
                        raise DirpyUserError(
                            "Each dimension must be defined only once")
                    dims[i] = o_dims[i]

        # If we were able to find some dimensions in our options array,
        # assign them to your req_dims classvar
        if len(dims) and dims != [None] * len(dims):
            self.req_dims = dims + [None]*(2-len(dims))
            self.num_dims = len(dims)
            return True

        return False


    # Get the post-gravity adjusted dimensions.  These can be bigger or 
    # smaller than the originally requested dimensions, 
    def _get_new_dims(self,opts): ############################################

        # Get our gravity, if any
        self.gravity = opts["gravity"] if "gravity" in opts else "c"

        # Check our gravity setting
        if self.gravity not in ("n","ne","e","se","s","sw","w","nw","c"):
            raise DirpyUserError("Unknown gravity: %s" % self.gravity)

        new_dims = [None, None, None, None]

        # Account for requested dimensions with only a single value set
        req_x = self.req_dims[0] or self.out_x
        req_y = self.req_dims[1] or self.out_y

        # Now calculate dimensions based on gravity
        if "w" in self.gravity:
            new_dims[0] = 0
        elif "e" in self.gravity:
            new_dims[0] = abs(self.out_x - req_x)
        else:
            new_dims[0]  = abs(self.out_x - req_x)/2

        if "n" in self.gravity:
            new_dims[1] = 0
        elif "s" in self.gravity:
            new_dims[1] = abs(self.out_y - req_y)
        else:
            new_dims[1]  = abs(self.out_y - req_y)/2

        new_dims[2] = new_dims[0] + min(req_x, self.out_x)
        new_dims[3] = new_dims[1] + min(req_y, self.out_y)

        return new_dims


    # Return perf data; this should be called after all other Dirpy
    # operations have been completed (although there is nothing stopping
    # you from calling it earlier).  We also send data to statsd here,
    # if applicable, since this seems like the best place to do it
    def yield_meta_data(self):
        self.meta_data["ms"]["time_total"] = time.time() - self.init_time

        # Convert all timings from fractional seconds to integer milliseconds
        self.meta_data["ms"] = { 
            k: int(v*1000) for k, v in self.meta_data["ms"].items() 
        }

        # Send to statsd if our statsd server has been configured
        if cfg.statsd_server is not None:
            udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            addr = (cfg.statsd_server, cfg.statsd_port)
            # Generate a list of our metrics with their statsd prefixes
            # attached.  Convert our fractional-second timing measurements
            # to milliseconds while we are at it
            pfx = cfg.statsd_prefix
            metrics = [ "%s.%s:%s|%s\n" % (
                    pfx, name.replace('_', '.', 1), val, met_type)
                for met_type, metrics in self.meta_data.items()
                for name, val in metrics.items()
            ]

            while metrics:
                buf = metrics.pop()
                while metrics and len(buf) + len(metrics[-1]) < 512:
                    buf += metrics.pop()

                try:
                    udp_sock.sendto(buf.rstrip().encode('utf-8'), addr)
                except Exception as e:
                    logger.debug("Failed to send to statsd: %s", e)
                    
        return json.dumps( 
            {x: y for i, j in self.meta_data.items() for x, y in j.items()}
        )

    # Serialize a specific subset of object values
    def serialize(self):
        serialized = {
            "meta_data":    pickle.dumps(self.meta_data),
            "out_fmt":      self.out_fmt,
            "out_size":     self.out_size,
            "out_buf":      self.out_buf.read()
        }
        self.out_buf.seek(0)

        return serialized

    # Deserialize a specific subset of object values
    def deserialize(self, redis_data):
        self.meta_data = pickle.loads(redis_data["meta_data"])
        self.out_fmt = redis_data["out_fmt"]
        self.out_size = redis_data["out_size"]
        self.out_buf.write(redis_data["out_buf"])
        self.out_buf.seek(0)

    # Our HTTP-specific result
    def result(self, http_code, http_msg=None):
        self.http_code = http_code
        self.http_msg  = http_msg

        return self


# HTTP Result code w/ matching string
class HttpResult(): ##########################################################
    codes = {
        200: "OK",
        204: "No Content",
        301: "Moved Permanently",
        302: "Found",
        304: "Not Modified",
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not Found",
        405: "Method Not Allowed",
        500: "Internal Server Error",
        501: "Not Implemented",
        502: "Bad Gateway",
        503: "Service Unavailable"
    }

    def __init__(self, http_code):
        self.http_code = http_code
        if http_code in self.codes:
            self.resultTxt = "%s %s" % (http_code, self.codes[http_code])
        else:
            self.resultTxt = str(http_code)


# Base Dirpy Error class
class DirpyError(Exception): #################################################
    def __init__(self, err_str, err_code=500):
        self.err_str = err_str
        self.err_code = err_code

    def __str__(self):
        return self.err_str


# Dirpy Fatal Error class
class DirpyFatalError(DirpyError): ###########################################
    pass    


# Dirpy User Error class
class DirpyUserError(DirpyError): ############################################
    pass


# Our HTTP Request handler class
class HttpHandler(http_server.BaseHTTPRequestHandler): #######################

    server_version = "Dirpy/" + __version__
    protocol_version = "HTTP/1.1"

    # Override log output (to stdout) and pass to our logger instance
    def log_message(self, format, *args):
        logger.debug("[%s] %s" % (
            multiprocessing.current_process().name, format % args))

    # Direct GET queries to http_worker
    def do_GET(self):
        http_worker(self)

    # Direct HEAD queries to http_worker
    def do_HEAD(self):
        http_worker(self, method="HEAD")

    # Direct POST queries to http_worker
    def do_POST(self):
        http_worker(self, method="POST")

    # Gracefully handle session failures
    def handle_one_request(self):
        try:
            http_server.BaseHTTPRequestHandler.handle_one_request(self)
        except:
            pass

    # Gracefully handle disconnects
    def finish(self,*args,**kw):
        try:
            if not self.wfile.closed:
                self.wfile.flush()
                self.wfile.close()
        except Exception:
            pass
        self.rfile.close()


# Our webserver class.  Implements timeouts
class HttpTimeoutServer(http_server.HTTPServer): ############################

    # Extend the HTTPServer constructor, so we can grab our timeout at init
    def __init__(self, server, handler, timeout=None):
        self.timeout = timeout
        http_server.HTTPServer.__init__(self, server, handler)

        # Set up our caching connection here, for lack of a better place
        redis_setup()

    # Bind our server and set our socket timeout before we accept connects
    def server_bind(self):
        try:
            http_server.HTTPServer.server_bind(self)
            self.socket.settimeout(self.timeout)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1) 
        except Exception as e:
            fatal("Failed to bind server: %s" % e)


# Store POST data in a BytesIO object instead of a temp file
class BytesIoStorage(cgi.FieldStorage):
    def make_file(self, binary=None):
        return io.BytesIO()


# Encapsulate our POST data and file
class PostData:
    def _init_(self, fp, env):
        self.form = BytesIoStorage(fq=fq, env=env)
        if not self.form['file'].filename:
            raise Excepton
        self.file_data = self.form['file']
        self.file_name = self.form['file'].filename
            

# The dirpy_worker wrapper function called when running in standalone mode
def http_worker(req, method="GET"): ##########################################

    # Read request URI as defined by the http_server path
    req_uri_obj = urlparse.urlparse(req.path)

    # Read post data, if need be
    if method == "POST":
        try:
            form = BytesIoStorage(
                fp=req.rfile,
                environ={'REQUEST_METHOD':'POST',
                         'CONTENT_TYPE':req.headers['Content-Type'],
                         })
            req_post_data = form['file'].file
        except Exception as e:
            return req.send_error(400, "Failed to read POST data: %s" % e)
    else:
        req_post_data = None

    # Call the dirpy worker
    result = dirpy_worker(req_uri_obj, req_post_data)

    # Handle 204/no-content responses
    if result.http_code == 204:
        req.send_response(204)
        req.send_header("Dirpy-Data", result.yield_meta_data())
        return
    # Throw an error if required
    elif result.http_msg is not None:
        req.send_error(result.http_code, result.http_msg)
        req.send_header("Dirpy-Data", result.yield_meta_data())
        return

    # Now fire off a response to our client
    req.send_response(200)
    req.send_header("Dirpy-Data", result.yield_meta_data())
    req.send_header("Content-Type", "image/%s" % result.out_fmt)
    req.send_header("Content-Length", str(result.out_size))
    req.end_headers()

    # Don't send actual data if this is a HEAD request
    if method == "HEAD":
        return

    # Guard against a broken TCP connection raising an exception
    # by wrapping the output buffer read/write loop in a try block
    try:
        while True:
            buf = result.out_buf.read(4096)
            if not buf:
                break
            req.wfile.write(buf)
    except:
        pass

    return


# The dirpy_worker wrapper function called when running in uwsgi mode
def application(env, resp): ##################################################

    # Read request URI from the UWSGI environment variable
    try:
        req_uri_obj = urlparse.urlparse(env["REQUEST_URI"])
    except Exception as e:
        resp("400 Bad Request", [("Content-Type","text/html")])
        return "Failure reading request data: %s" % e

    # Handle POST data, if any
    if "REQUEST_METHOD" in env and env["REQUEST_METHOD"].upper() == "POST":
        try:        
            form = BytesIoStorage(fp=env['wsgi.input'], environ=env)
            req_post_data = form['file'].file
        except Exception as e:
            resp("400 Bad Request", [("Content-Type","text/html")])
            return "Failure reading POST data: %s" % e
    else:
        req_post_data = None
            
    # Call the dirpy worker
    result = dirpy_worker(req_uri_obj, req_post_data)
    http_res = HttpResult(result.http_code)

    # Handle 204/no-content responses
    if result.http_code == 204:
        resp(http_res.resultTxt, [
            ("Dirpy-Data", result.yield_meta_data()),
            ("Content-Type","text/html")
        ])
        return ""

    # Handle any errors
    elif result.http_msg is not None:
        resp(http_res.resultTxt, [
            ("Dirpy-Data", result.yield_meta_data()),
            ("Content-Type","text/html")
        ])
        return result.http_msg

    # Now fire off a response to our client
    logger.debug("out_size: %s" % result.out_size)
    resp("200 OK", [
        ("Dirpy-Data", str(result.yield_meta_data())),
        ("Content-Type", "image/%s" % str(result.out_fmt)),
        ("Content-Length", str(result.out_size)) ]
    )

    if result.out_buf is not None:
        return result.out_buf.read()

    return ""
    

# Our dirpy function.  This is where all the heavy lifting is done
def dirpy_worker(req_uri_obj, req_post_data): ################################

    # Extract relative file path and full query path from request URI object
    file_path = req_uri_obj.path
    query_path = "%s/%s" % (req_uri_obj.path, req_uri_obj.query)

    # Instatiate our dirpy image object
    dirpy_obj = DirpyImage(cfg.http_root)

    # Ignore favicons
    if file_path == "/favicon.ico":
        return dirpy_obj.result(204)

    # Non-positional arguments
    args = { "load": {}, "save": {} }

    # Positional-based commands
    cmds = get_cmds(req_uri_obj, args)
    logger.debug("Got request: %s" % cmds)

    # Check for a status request, ignore everything else if we get one
    if any(cmd[0] == "status" for cmd in cmds):
        return dirpy_obj.result(204)

    # If our cache client exists, try to fetch from it first
    # Don't use cache on POST requests, though
    if redis_client and not req_post_data:
        cache_key = hashlib.sha1(cfg.redis_prefix + query_path).hexdigest()
        logger.debug("Looking for cache key %s" % cache_key)
        try:
            cache_start = time.time()
            result = redis_client.hgetall(cache_key)
            if result:
                logger.debug("Serving request via redis")
                dirpy_obj.deserialize(result)
                dirpy_obj.meta_data["c"]["cache_hit"] = 1

                # Remove timing parameters to prevent cache
                # hits from skewing timing graphs
                dirpy_obj.meta_data.pop("ms", None)

                # Now set the time taken to serve a cached request
                dirpy_obj.meta_data["ms"]["time_cache_read"] = (time.time()
                    - cache_start)

                return dirpy_obj.result(200, None)
            else:
                logger.debug("Cache miss; serving file normally")
        except Exception as e:
            logger.debug("Failed to read from redis: %s" % e)

    # Catch dirpy-related errors
    try:
        # Load our image
        dirpy_obj.load(args["load"], file_path, req_post_data)

        # Now run our requested commands & options against the dirpy image
        for cmd, opts in cmds:
            dirpy_obj.run(cmd, opts)

        # Now save it to an output buffer
        dirpy_obj.save(args["save"])

    except DirpyFatalError as e:
        logger.warning(str(e))
        return dirpy_obj.result(e.err_code, "Fatal Dirpy Error")
    except DirpyUserError as e:
        logger.debug(str(e))
        return dirpy_obj.result(e.err_code, e.err_str)
    except Exception as e:
        logger.warning(traceback.format_exc())
        return dirpy_obj.result(503, "Uncaught Dirpy Error")

    # Return 204/No CONTENT if the file is zero length.  This should
    # only happen using the "noshow" option for the save command
    if str(dirpy_obj.out_size) == "0":
        return dirpy_obj.result(204)

    # Write to our redis client, if it exists
    if redis_client and not req_post_data:
        logger.debug("Writing result to redis")
        cache_start = time.time()
        try:
            redis_client.hmset(cache_key, dirpy_obj.serialize())
            dirpy_obj.meta_data["c"]["cache_write"] = 1

        except Exception as e:
            logger.debug("Failed to write to redis: %s" % e)

        dirpy_obj.meta_data["ms"]["time_cache_write"] = (time.time()
            - cache_start)

    return dirpy_obj.result(200, None)


# Read in the command line and file based configuration parameters
def read_config(uwsgi_cfg=None): #############################################

    # Build our config parser
    parser = argparse.ArgumentParser(
        description="DIRPY: the Dynamic Image Resizing Program, Yay!")
    parser.add_argument("-c", "--config-file",
        help="Path to the Dirpy config file")
    parser.add_argument("-d", "--debug", action="store_true",
        help="Emit debug output")
    parser.add_argument("-f", "--foreground", action="store_true",
        help="Don't daemonize; run program in the foreground")

    # Parse command line
    global cfg
    cfg = parser.parse_args()

    # Config file precedence: 
    # uwsgi_cfg >> cfg.config_file >> "/etc/dirpy.conf" 
    # If a user-defined config file (i.e. uwsgi_cfg or cfg.config_file) is
    # defined but not exist, we should throw a fatal error
    cfg_file = uwsgi_cfg or cfg.config_file or "/etc/dirpy.conf"
    cfg_parser = configparser.RawConfigParser()
    try:
        if cfg_parser.read(cfg_file):
            cfg.defaults = False
        else:
            cfg.defaults = True
    except Exception as e:
        fatal("Unable to load config file '%s': %s" % (cfg_file, e))

    # Read in all of our global / default options
    cfg.pid_file                = cfg_str(cfg_parser,
        "global", "pid_file", False, "/var/run/dirpy.pid")
    cfg.log_file                = cfg_str(cfg_parser,
        "global", "log_file", False, "/var/log/dirpy.log")
    cfg.log_max_line            = cfg_int(cfg_parser,
        "global", "log_max_line", False, 300)
    cfg.bind_addr               = cfg_str(cfg_parser,
        "global", "bind_addr", False,  "0.0.0.0")
    cfg.bind_port               = cfg_int(cfg_parser,
        "global", "bind_port", False,  3000)
    cfg.http_root               = cfg_str(cfg_parser,
        "global", "http_root", False,  "/var/www/html")
    cfg.num_workers             = cfg_int(cfg_parser,
        "global", "num_workers", False,  multiprocessing.cpu_count()*2)
    cfg.max_pixels              = cfg_int(cfg_parser,
        "global", "max_pixels", False,  90000000)
    cfg.def_quality             = cfg_int(cfg_parser,
        "global", "def_quality", False,  95)
    cfg.min_recompress_pixels   = cfg_int(cfg_parser,
        "global", "min_recompress_pixels", False,  0)
    cfg.req_timeout             = cfg_int(cfg_parser,
        "global", "req_timeout", False, None)
    cfg.allow_post              = cfg_bool(cfg_parser,
        "global", "allow_post", False,  False)
    cfg.allow_todisk            = cfg_bool(cfg_parser,
        "global", "allow_todisk", False, False)
    cfg.allow_mkdir             = cfg_bool(cfg_parser,
        "global", "allow_mkdir", False, False)
    cfg.allow_overwrite         = cfg_bool(cfg_parser,
        "global", "allow_overwrite", False, False)
    cfg.todisk_root             = cfg_str(cfg_parser,
        "global", "todisk_root", False,  "/nonexistant")
    cfg.statsd_server           = cfg_str(cfg_parser,
        "global", "statsd_server", False, None)
    cfg.statsd_port             = cfg_int(cfg_parser,
        "global", "statsd_port", False, 8125)
    cfg.statsd_prefix           = cfg_str(cfg_parser,
        "global", "statsd_prefix", False, "dirpy")
    cfg.redis_hosts             = cfg_str(cfg_parser,
        "global", "redis_hosts", False, None)
    cfg.redis_cluster           = cfg_bool(cfg_parser,
        "global", "redis_cluster", False, False)
    cfg.redis_prefix            = cfg_str(cfg_parser,
        "global", "redis_prefix", False, "dirpy")
    cfg.debug                   = cfg_bool(cfg_parser,
        "global", "debug", False, cfg.debug)


# Extract dirpy arguments and positional commands/options from the
# parsed query string
def get_cmds(parsedPath, args): ##############################################
    
    # Now parse the query string and turn it into our command/option data
    # structure.  This should allow for commands and their options to be
    # passed in the format: cmd1=opt1:val1,opt2,opt3:val3&cmd2=opt4:val4
    # Note that option/value pairs are comma delimited, and the actual
    # options and values are semi-colon delimited.  Option values are
    # optional, with a True value being subsitituted if they do not exist.
    # Also, commands are not uniquely constained (i.e. they can be repeated)

    cmds = []

    for fv_pair in parsedPath.query.split("&"):
        fv_norm = urllib.unquote(fv_pair).decode("utf-8")
        oper = None
        opts = {}
        if "=" in fv_pair:
            oper, all_opts = fv_norm.split("=",1)
            for opt_str in all_opts.split(","):
                if ":" in opt_str:
                    opt_pair = opt_str.split(":",1)
                    opts[opt_pair[0]] = opt_pair[1]
                else:
                    opts[opt_str] = True
        else:
            oper, opts = fv_norm, {}

        if oper in args:
            args[oper] = opts
        else:
            cmds.append([oper, opts])


    return cmds


# Grab an string from our config
def cfg_str(cfg, section, name, required=True, default=None): ################
    try:
        return cfg.get(section, name)
    except configparser.Error:
        if not required:
            return default
        fatal("Missing required config parameter %s:%s." % (section, name))


# Grab an int from our config, complain if it isn't valid
def cfg_int(cfg, section, name, required=True, default=None): ################
    try:
        # Allow a string if they match the default value
        return cfg.getint(section, name)
    except ValueError:
        fatal("Config parameter %s:%s must be an integer." % (section, name))
    except configparser.Error:
        if not required:
            return default
        fatal("Missing required config parameter %s:%s." % (section, name))


# Grab an int from our config, complain if it isn't valid
def cfg_bool(cfg, section, name, required=True, default=False): ##############
    try:
        # Allow a string if they match the default value
        return cfg.getboolean(section, name)
    except ValueError:
        fatal("Config parameter %s:%s must be a boolean." % (section, name))
    except configparser.Error:
        if not required:
            return default
        fatal("Missing required config parameter %s:%s." % (section, name))


# Grab an network address from our config, complain if it isn't valid
def cfg_addr(cfg, section, name, required=True, default=None): ###############
    # Fetch and validate a hostname/ip address config option
    try:
        addr = cfg.get(section, name)
        socket.gethostbyname(addr)
        return addr
    except configparser.Error:
        if not required:
            return default
        fatal("Missing required config parameter %s:%s." % (section, name))
    except socket.gaierror:
        fatal("Invalid address for config parameter %s:%s" % (section, name))


# Make outgoing log messages printable and enforce a maximum line length
class DirpyLogFilter(logging.Filter): ########################################
    def __init__(self, log_max_line):
        self.log_max_line = log_max_line
    def filter(self, rec):
        rec.msg = rec.msg.encode('utf_8').decode('unicode_escape')
        if len(rec.msg) > self.log_max_line:
            rec.msg = rec.msg[:self.log_max_line-3] + "..."

        return True
        

# Set up our global logger
def logger_setup(): ##########################################################

    # Set our maximum severity level to log (i.e. debug or not)
    logLevel = logging.DEBUG if cfg.debug else logging.INFO
    if cfg.foreground:
        logFh = sys.stdout
    else:
        try:
            logFh = open(cfg.log_file, "a")
        except IOError as e:
            fatal("Unable to log to %s (%s)" % (cfg.log_file, e.strerror))

    logging.basicConfig(
        stream=logFh,
        level=logLevel,
        format="%(asctime)s %(levelname)s: [%(process)d] %(message)s",
        datefmt="[%Y-%m-%d@%H:%M:%S]"
    )

    global logger
    logger = logging.getLogger("dirpy")
    log_filter = DirpyLogFilter(cfg.log_max_line)
    logger.addFilter(log_filter)

    # Make the logger emit all unhandled exceptions
    # sys.excepthook = lambda t, v, x: logger.exception(str(v))

    if cfg.defaults:
        logger.info("Can't read config file %s; using default values" %
            cfg.config_file)


# Extract a host/port pair from a redis host declaration
def redis_host_port(host_port):
    if ":" in host_port:
        host, port = host_port.split(":")
        try:
            port = int(port)
        except:
            fatal("Redis port must be an integer: %s" % (host_port))
    else:
        host = host_port
        port = 6379

    return host, str(port)

# Set up caching layer, if requested by user
def redis_setup(): ###########################################################

    global redis_client
    redis_client = None

    if not cfg.redis_hosts: return

    if cfg.redis_cluster:
        try:
            import rediscluster
        except:
            fatal("Redis cluster support requires the "
                "'redis-py-cluster' python module.")

        logger.debug("Connecting to redis cluster using: %s" % cfg.redis_hosts)

        startup_nodes = []
        for host_port in [x.strip() for x in cfg.redis_hosts.split(',')]:
            host, port = redis_host_port(host_port)
            startup_nodes.append({"host": host, "port": port})

        try:
            redis_client = rediscluster.StrictRedisCluster(
                startup_nodes=startup_nodes, decode_responses=False)
        except Exception as e:
            fatal("Error connecting to redis cluster: %s" % e)

    else:
        try:
            import redis
        except:
            fatal("Redis support requires the 'redis' python module.")

        logger.debug("Connecting to redis host: %s" % cfg.redis_hosts)

        if "," in cfg.redis_hosts:
            fatal("Multiple redis hosts not permitted in non-cluster mode")

        host, port = redis_host_port(cfg.redis_hosts)

        try:
            redis_client = redis.StrictRedis(host=host, port=port)
        except Exception as e:
            fatal("Error connecting to redis backend: %s" % e)


# Throw a fatal message and exit
def fatal(msg): ##############################################################

    try:
        logger
    # If our logger isnt defined, print directly to stdout
    except:
        ts = datetime.datetime.now().strftime("%Y-%m-%d@%H:%M:%S")
        print("[%s] CRITICAL: %s" % (ts, msg))
    # Otherwise, just use the logger
    else:
        logger.critical(msg)

    sys.exit(1)


# Launch our process as a daemon
def daemonize(): #############################################################

    UMASK = 0
    MAXFD = 1024

    # Fork once
    try:
        pid = os.fork()
    except OSError as e:
        fatal("Unable to fork: %s [%d]" % (e.strerror, e.errno))

    # In the first child process
    if (pid == 0):
        os.setsid()

        try:
            pid = os.fork()
        except OSError as e:
            fatal("Unable to fork: %s [%d]" % (e.strerror, e.errno))

        if (pid == 0):
            os.chdir("/")
            os.umask(UMASK)
        else:
            os._exit(0)
    else:
        os._exit(0)

    # Close all open file descriptors
    for fd in range(0, MAXFD):
        try:
            os.close(fd)
        except OSError:
            pass

    # DUP our stdout & stderr filehandles to dev null
    os.open(os.devnull, os.O_RDWR)
    os.dup2(0, 1)
    os.dup2(0, 2)

    return


# Spawn a worker process, along with the time that it was started
def spawn_worker(target, args): ##############################################

    # Try three times to start a worker, and then give up
    attempts = 3
    while attempts > 0:
        try:
            worker = multiprocessing.Process(target=target, args=args)
            worker.daemon = True
            worker.start()
            return [worker, time.time()]

        # Sad lack of Python documentation for multiprocessing exceptions...
        except Exception as e:
            attempts -= 1
            logger.info("Failed to spawn worker (%s); %s more attempt(s)" %
                (e, attempts))
            time.sleep(1)

    # Uh oh, can't spawn a worker.  Time to shut down 
    fatal("Unable to spawn worker after %s attempts" % attempts)


# The serve_forever wrapper, called by multiprocessing.Process
def server_wrapper(server): ##################################################
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


# Our main loop, used in standalone mode
def dirpy_main(): ############################################################

    # Read command line parameters and config file
    read_config()

    # Daemonize, unless requested otherwise
    if not cfg.foreground:
        daemonize()

    # Start our logger
    logger_setup()

    # Catch SIGINTs
    signal.signal(signal.SIGINT, lambda s, f: os._exit(1))

    # Drop our pid file if we are daemonized
    if not cfg.foreground:
        try:
            with open(cfg.pid_file, "w") as fh:
                fh.write(str(os.getpid()))
        except IOError as e:
            fatal("Unable to write to pidfile %s (%s)" % (cfg.pid_file, e))

    # Initialize our http server class
    http_server = HttpTimeoutServer(
        (cfg.bind_addr, cfg.bind_port), HttpHandler, cfg.req_timeout)

    # Start our worker pool.  We dont use multiprocessing.pool, since we want
    # to be able to watchdog our server processes
    workers = []
    for i in range(cfg.num_workers):
        workers.append(spawn_worker(server_wrapper, (http_server,)))

    # We're up and running; let the world know about it
    logger.info("Dirpy daemon started! Herp da dirp!")
    logger.info("Listing on %s:%s, using %s worker(s) " %
        (cfg.bind_addr, cfg.bind_port, cfg.num_workers))

    # Enter watchdog mode
    while True:
        time.sleep(1)
        
        # Check to see if any workers have died/exited unexpectedly
        for i in range(cfg.num_workers):

            # If a worker exited; clean up after it and then restart it
            if not workers[i][0].is_alive():
                logger.error("Worker %s died; restarting it." % (i+1,))
                workers[i][0].join()
                workers[i] = spawn_worker(server_wrapper, (http_server,))

    # Shouldn't ever get this far, but just in case...
    sys.exit(1)


# Handle being launched via UWSGI
def uwsgi_prep(): ###########################################################

    import uwsgi

    # Read command line args
    if "dirpy_cfg" in uwsgi.opt:
        read_config(uwsgi.opt["dirpy_cfg"])
    else:
        read_config()

    # Set up our logger
    logger_setup()

    # Let the world know that we have started
    logger.info("Dirpy v%s uWSGI worker started! Herp da dirp!"
            % __version__)

    # Set up our cache client (if any)
    redis_setup()


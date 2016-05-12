# Design


## Choosing a solution

Once it became clear that a dynamic resizing option would be highly desirable (an most likely required in an expedient manner), we began investigating the various available options.  The first immediately visible option was the [Akamai Image Converter](http://www.akamai.com/html/technology/image-converter.html).  This was quickly ruled out as an option, as the setup time was deemed to be too long (months) as well as cost prohibitive (requiring switching from Edgecast to Akamai as our imaging CDN).

The second (and perhaps least complicated) option considered was using the [GraphicsMagick Nginx filter module](https://github.com/believe3301/ngx-gm-filter) to resize images.  This approach had the benefit of plugging neatly into our existing infrastructure, with minimal changes (requiring only a recompiled version of Nginx).  As GraphicsMagick is the performance-based fork the popular ImageMagick tool suite, it was expected that performance would be excellent.  Initial benchmarks, however, we very disappointing, and so we continued to look for alternatives.

Next, we began investigating the [VIPS library](http://www.vips.ecs.soton.ac.uk/) (oft mentioned online for its high-performance image manipulation abilities).  Specifically, we investigated both the Node.js VIPS binding (named [Sharp](https://github.com/lovell/sharp)) and the VIPS Python module (included with the VIPS installation).  The Sharp version of the image resizer was a very svelte program (measuring only 200 lines of code) and was indeed very performant (beating the Nginx GraphicsMagick module by a factor of three).  

However, repeated stress testing on the Sharp-based resizer soon revealed that it suffered from unbounded memory growth, and would eventually crash due to memory exhaustion issues.  Despite collaboration with both the Sharp and the VIPS maintainers, heapdump comparisons, and several dozen hours spent debugging the Sharp and VIPS functions involved, we were unable to ascertain the root cause of the memory growth.  Worse, the Python VIPS bindings were found to be extremely limited (missing several key functions that were required for our resizing operations) and thus we were forced to discard any VIPS-based solution as a viable option.

Our final (and, ultimately, preferred) solution was one based on the ["Pillow" fork of the Python Imaging Library (PIL)](https://pillow.readthedocs.org/en/latest/).  While not as well-known as GraphicsMagick or VIPS, it is highly performant, and (after being dropped into an existing server framework used by Ops for other projects) proved to be the best candidate for image resizing, having superior resizing speed, CPU utilization and memory consumption when compared to the other options.


## Implemented Solution

The completed Python+PIL-based solution, codenamed "Dirpy", consists of a single watchdog process, which launches a user-configurable number of persistent worker sub-processes. The workers are responsible for decoding the HTTP request, fetching the source image (either from disk or by proxying to a remote server), and then performing the requested resizing operations.

Using a pool of workers, instead of spawning a new process for every incoming request, has the following advantages:
Prevents the startup cost associated with new process construction.
Allows for a FIFO-like queuing system (ensuring that earlier requests are serviced first)
Allows for an easy method to limit resource utilization on the machine hosting the resizing daemon.   

The worker pool used by Dirpy is constructed via the multiprocessing.pool Python method, allowing us to bypass the parallelism-thwarting problems introduced by the Python global interpreter lock.

Multiple Python HTTP server modules were explored, however the BaseHTTPServer module included with Python proved to be sufficient for our needs, as it supported listening from multiple subprocess, as well as other niceties like HTTP/1.1 support.  In all scenarios, the resizing portion of the process will be the limiting factor in transaction times, thus a high-performance, non-standard HTTP module (such as uwsgi, gevent or FAPWS3) only add unnecessary prerequisites to the image server.

The PIL module (depending on which libraries are available when it is installed) can decode and encode a large number of image formats.  This should provide us with considerable agility in the future, if MLSs begin using non-jpeg image formats.  Incoming image formats are auto-detected by Dirpy, and are used as the output format unless otherwise requested.

The PIL module also supports several different downsampling filters, which, when listed in terms of decreasing speed (but increasing quality), are: Nearest, Bilinear, Bicubic, and Antialias (a tri-lobed Lanczos filter).  All filters provide acceptable downsampled images with little-to-no artifacting or moire patterns, but the Antialias filter provides the best image type (and is comparable with the one already used by the existing photo importers for resizing) and thus is set as the default filter (although Dirpy can be configured to use one of the other filters).

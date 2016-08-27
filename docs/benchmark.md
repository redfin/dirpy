# Benchmarks

The following guidelines were closely followed when performing
comparative benchmarks between the various options:

- Benchmarks were performed using a dedicated test VM consisting of 4 cores
  and 4GB.
- A large corpus of 2+ million target URLs (consisting of all current image 
  sizes & types) were then run through each option 5 times, taking note of the
  runtime, CPU utilization and RAM consumption of each iteration.
- Requests were made in a highly-parallel fashion (using Siege to provide a 
  queue depth of 16) in an attempt to simulate heavy user traffic and
  ascertain the high watermark values for each metric.
- Requests were made over a dedicated network connection, to prevent traffic 
  contention from skewing test results
- Disk cache was cleared prior to running each test iteration to force all 
  tests to load each image from disk.
- CPU and memory metrics were collected using the 'pidstat' program from the
  CentOS 'sysstat' package.

Command

    siege -f <url_corpus_file> -c 100 -b

## Results

### Run times (in seconds)
|               | Run 1  | Run 2  | Run 3  | Run 4  | Run 5  | Avg    | Avg Images/sec |
| ------------- | ------ | ------ | ------ | ------ | ------ | ------ | -------------- |
| Node+Sharp    | 58.28  | 56.38  | 56.82  | 57.67  | 61.28  | 58.09  | 129.22         |
| Python+PIL    | 49.28  | 49.83  | 47.40  | 47.48  | 47.05  | 48.21  | 155.70         |
| Nginx+Gmagick | 215.94 | 191.23 | 192.14 | 187.40 | 196.23 | 196.59 | 38.18          |

### % Avg CPU Utilization
|                 | Run 1  | Run 2  | Run 3  | Run 4  | Run 5  | Avg    |
| --------------- | ------ | ------ | ------ | ------ | ------ | ------ |
| Node+Sharp      | 190.40 | 252.80 | 249.00 | 256.60 | 251.40 | 240.04 |
| Python+PIL      | 136.60 | 138.20 | 139.40 | 142.00 | 143.00 | 139.84 |
| Nginx+Gmagick   | 384.10 | 395.20 | 391.70 | 389.10 | 394.10 | 390.84 |

### % Avg RAM Utilization
|                 | Run 1 | Run 2 | Run 3 | Run 4 | Run 5 | Avg   |
| --------------- | ----- | ----- | ----- | ----- | ----- | ----- |
| Node+Sharp      | 19.99 | 27.59 | 43.41 | 50.32 | 57.47 | 39.76 |
| Python+PIL      | 1.76  | 1.68  | 1.59  | 1.64  | 1.63  | 1.66  |
| Nginx+Gmagick   | 2.61  | 2.70  | 2.71  | 2.56  | 2.76  | 2.67  |

The Python+PIL option was the obvious "winner" in each metric.  Also of 
interest is the RAM consumption values for the Sharp-based image resizer, 
where you can see the memory usage of the resizer growing at a monotonic 
(and rather rapid) rate with each subsequent test.

Furthermore, the [Pillow-SIMD](https://github.com/uploadcare/pillow-simd),
fork has shown some very promising performance increases.  Using CPUs enabled
with generic SSE2 extensions, we were able to achieve a 10% increase in
query speed, with a corresponding decrease in CPU utilization (memory 
usage remained the same, however).  We are still waiting to run tests against
processors with AVX2 extensions (which should realize even more impressive
performance gains), but for the moment we can heartily recommend using
Pillow-SIMD in place of the standard Pillow module.

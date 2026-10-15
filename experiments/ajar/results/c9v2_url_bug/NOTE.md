config_m1_c9v2 on kernel aca4390: SUPERSEDED. The request-literal check (9.2 R) compared strings
literally, so a URL the request names (www.informations.com) called with a scheme
(http://www.informations.com) was "neither from the request nor own" — slack benign user tasks 0, 3,
19 lost. Fixed in axor-core 2660994 (matched as L1 reads it); recomputed as c9v2b.

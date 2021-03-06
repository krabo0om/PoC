
cache_par
#########

All inputs are synchronous to the rising-edge of the clock `clock`.
Command truth table:
Request | ReadWrite | Invalidate	| Replace | Command
--------+-----------+-------------+---------+--------------------------------
	0			|		0				|		0					|		0			| None
	1			|		0				|		0					|		0			| Read cache line
	1			|		1				|		0					|		0			| Update cache line
	1			|		0				|		1					|		0			| Read cache line and discard it
	1			|		1				|		1					|		0			| Write cache line and discard it
	0			|		-				|		0					|		1			| Replace cache line.
--------+-----------+-------------+------------------------------------------
All commands use `Address` to lookup (request) or replace a cache line.
`Address` and `OldAddress` do not include the word/byte select part.
Each command is completed within one clock cycle, but outputs are delayed as
described below.
Upon requests, the outputs `CacheMiss` and `CacheHit` indicate (high-active)
whether the `Address` is stored within the cache, or not. Both outputs have a
latency of one clock cycle.
Upon writing a cache line, the new content is given by `CacheLineIn`.
Upon reading a cache line, the current content is outputed on `CacheLineOut`
with a latency of one clock cycle.
Upon replacing a cache line, the new content is given by `CacheLineIn`. The
old content is outputed on `CacheLineOut` and the old tag on `OldAddress`,
both with a latency of one clock cycle.


.. rubric:: Entity Declaration:

.. literalinclude:: ../../../src/cache/cache_par.vhdl
   :language: vhdl
   :tab-width: 2
   :linenos:
   :lines: 70-94

Source file: `cache/cache_par.vhdl <https://github.com/VLSI-EDA/PoC/blob/master/src/cache/cache_par.vhdl>`_


 


ddrio_inout
###########

Instantiates chip-specific DDR input and output registers.

Both data "DataOut_high/low" as well as "OutputEnable" are sampled with
the rising_edge(Clock) from the on-chip logic. "DataOut_high" is brought
out with this rising edge. "DataOut_low" is brought out with the falling
edge.

"OutputEnable" (Tri-State) is high-active. It is automatically inverted if
necessary. Output is disabled after power-up.

Both data "DataIn_high/low" are synchronously outputted to the on-chip logic
with the rising edge of "Clock". "DataIn_high" is the value at the "Pad"
sampled with the same rising edge. "DataIn_low" is the value sampled with
the falling edge directly before this rising edge. Thus sampling starts with
the falling edge of the clock as depicted in the following waveform.
             __      ____      ____      __
Clock          |____|    |____|    |____|
Pad          < 0 >< 1 >< 2 >< 3 >< 4 >< 5 >
DataIn_low      ... >< 0      >< 2      ><
DataIn_high     ... >< 1      >< 3      ><

< i > is the value of the i-th data bit on the line.

"Pad" must be connected to a PAD because FPGAs only have these registers in
IOBs.


.. rubric:: Entity Declaration:

.. literalinclude:: ../../../../src/io/ddrio/ddrio_inout.vhdl
   :language: vhdl
   :tab-width: 2
   :linenos:
   :lines: 66-84

Source file: `io/ddrio/ddrio_inout.vhdl <https://github.com/VLSI-EDA/PoC/blob/master/src/io/ddrio/ddrio_inout.vhdl>`_


 

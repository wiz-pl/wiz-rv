// A test bench for the Doom machine's simulation top (`simTop`, src/Rv/Doom.wiz: the
// core at half rate, the bus adapter, a DDR model): it sends the bytes of rx.hex to
// uart_rx at 1 Mbaud (100 clocks a bit), prints what comes back on uart_tx, and stops
// after `cycles` clocks (+cycles=N).
`timescale 1ns/1ps
module tb;
  reg clk = 0;
  always #5 clk = ~clk;
  reg rx = 1;
  wire tx;
  wire [3:0] led;
  wire [7:0] ja, jb;
  doom_sim dut(.clk(clk), .uart_rx(rx), .uart_tx(tx), .led(led), .ja(ja), .jb(jb));
  reg [7:0] bytes [0:1048575];
  integer n, i, b, cycles;
  initial begin
    for (i = 0; i < 1048576; i = i + 1) bytes[i] = 8'hxx;
    $readmemh("rx.hex", bytes);
    if (!$value$plusargs("cycles=%d", cycles)) cycles = 2000000;
    repeat (20000) @(posedge clk);
    for (i = 0; bytes[i] !== 8'hxx; i = i + 1) begin
      rx = 0; repeat (100) @(posedge clk);
      for (b = 0; b < 8; b = b + 1) begin rx = bytes[i][b]; repeat (100) @(posedge clk); end
      rx = 1; repeat (100) @(posedge clk);
    end
  end
  // the receiver: a falling edge, then the middle of each bit
  reg [7:0] c;
  integer k;
  initial begin
    forever begin
      @(negedge tx);
      repeat (150) @(posedge clk);
      for (k = 0; k < 8; k = k + 1) begin c[k] = tx; repeat (100) @(posedge clk); end
      $write("%c", c); $fflush;
    end
  end
  initial begin
    repeat (cycles) @(posedge clk);
    $display("\n[tb] %0d cycles, led %b", cycles, led);
    $finish;
  end
endmodule

// A test bench for the OLED framebuffer and controller on their own (`oled_fb`, written
// by app/oledgen.wiz from `OledFb.circuit`, src/Rv/OledFb.wiz; the simulation's short
// waits, frames back to back, a controller step every clock). Run by scripts/oled-sim.sh.
//
// It decodes the PmodOLEDrgb's SPI from JA (PMODEN VCCEN RES D/C SCLK 0 MOSI CS, bit 7 … 0)
// the way the SSD1331 does (Solomon Systech SSD1331 rev 1.2, section 8.1.3, 4-wire SPI:
// MOSI sampled on SCLK's rising edge, most significant bit first, D/C# sampled with the
// last bit, CS# low for the whole byte) and checks:
//   * the timing rules: MOSI and D/C# steady at every rising edge, CS# never raised in a
//     byte, no clock while CS# is high;
//   * the power-on command stream (the settings of src/Rv/Oled.wiz, RProg.settings, then
//     the window, a blank frame and display on once VCCEN is high);
//   * every refresh: CS# low, the window commands 15 00 5F 75 00 3F, then exactly
//     96 × 64 pixels as 2 data bytes each, then CS# high;
//   * the pixels: the bench writes frame k as the value k·8192 + i at pixel i, so every
//     pixel the panel receives names its frame and must name its own position (catches
//     any addressing, row or column order fault), and a refresh that holds more than one
//     frame is torn.
// The scenario: frame 1 into bank 0 at power-on; frame 2 into bank 0 in the middle of
// refresh 1, as software without double buffering does (refresh 1 must come out torn:
// that is the board's artefact); then frame 3 into bank 1 in the middle of refresh 3 and
// `show` = 1, frame 4 into bank 0 in the middle of refresh 4 and `show` = 0 (refreshes
// 3, 4, 5 must be whole frames 2, 3, 4).
`timescale 1ns/1ps
module tb;
  reg clk = 0;
  always #5 clk = ~clk;
  reg we = 0, cw = 0, cd = 0;
  reg [13:0] wa = 0;
  reg [15:0] wd = 0;
  wire [7:0] ja;
  wire front, show;
  oled_fb dut(.clk(clk), .we(we), .wa(wa), .wd(wd), .cw(cw), .cd(cd), .ja(ja), .front(front), .show(show));

  wire dc = ja[4], sclk = ja[3], mosi = ja[1], cs = ja[0], vccen = ja[6];

  integer errors = 0;
  task fail(input [8*96-1:0] what); begin errors = errors + 1; if (errors <= 20) $display("[tb] ERROR %0s", what); end endtask

  // the expected power-on commands (src/Rv/Oled.wiz: RProg.settings, the window)
  reg [7:0] initCmds [0:63];
  integer nInit;
  initial begin
    nInit = 0;
    `define C(b) begin initCmds[nInit] = b; nInit = nInit + 1; end
    `C(8'hFD) `C(8'h12) `C(8'hAE) `C(8'hA0) `C(8'h72) `C(8'hA1) `C(8'h00) `C(8'hA2) `C(8'h00)
    `C(8'hA4) `C(8'hA8) `C(8'h3F) `C(8'hAD) `C(8'h8E) `C(8'hB0) `C(8'h0B) `C(8'hB1) `C(8'h31)
    `C(8'hB3) `C(8'hF0) `C(8'h8A) `C(8'h64) `C(8'h8B) `C(8'h78) `C(8'h8C) `C(8'h64) `C(8'hBB)
    `C(8'h3A) `C(8'hBE) `C(8'h3E) `C(8'h87) `C(8'h06) `C(8'h81) `C(8'h91) `C(8'h82) `C(8'h50)
    `C(8'h83) `C(8'h7D) `C(8'h2E) `C(8'h15) `C(8'h00) `C(8'h5F) `C(8'h75) `C(8'h00) `C(8'h3F)
  end
  reg [7:0] window [0:5];
  initial begin
    window[0] = 8'h15; window[1] = 8'h00; window[2] = 8'h5F;
    window[3] = 8'h75; window[4] = 8'h00; window[5] = 8'h3F;
  end

  // the SPI receiver, sampled between clock edges
  reg pSclk = 1, pMosi = 0, pDc = 0, pCs = 1;
  integer nbits = 0;
  reg [7:0] sh = 0;
  reg byteDc = 0;
  // the stream: phase 0 power-on commands, 1 the blank frame, 2 display on, 3 refreshes
  integer phase = 0, k = 0, nCmd = 0, nData = 0, csLowBytes = 0;
  integer refresh = 0;        // refreshes started (CS# low after display on)
  integer rCmd = 0, rData = 0;
  reg [7:0] hiByte;
  integer framesSeen [0:7];
  integer tagFirst, tagCount, j;
  reg [15:0] pix;
  integer torn [0:15], tagOf [0:15], whole [0:15];
  integer sclkWhileCsHigh = 0;
  integer bytesTotal = 0;
  integer frontChanges = 0;
  reg pFront = 0;

  task endRefresh; begin
    if (refresh > 0) begin
      if (rCmd != 6) fail("a refresh without exactly 6 window command bytes");
      if (rData != 12288) begin
        $display("[tb] refresh %0d: %0d data bytes", refresh, rData);
        fail("a refresh without exactly 12288 data bytes");
      end
      tagCount = 0;
      for (j = 0; j < 8; j = j + 1) if (framesSeen[j] > 0) tagCount = tagCount + 1;
      $write("[tb] refresh %0d: %0d command + %0d data bytes, frames", refresh, rCmd, rData);
      for (j = 0; j < 8; j = j + 1) if (framesSeen[j] > 0) $write(" %0d×%0d", j, framesSeen[j]);
      $display("%0s", tagCount > 1 ? "  TORN" : "");
      if (refresh < 16) begin torn[refresh] = tagCount > 1; tagOf[refresh] = tagFirst; whole[refresh] = rData == 12288; end
    end
  end endtask

  always @(negedge clk) begin
    if (!cs && sclk && !pSclk) begin
      // a rising edge: MOSI and D/C# must have been steady since the last sample
      if (mosi !== pMosi) fail("MOSI changed with SCLK's rising edge");
      if (nbits > 0 && dc !== byteDc) fail("D/C# changed within a byte");
      if (nbits == 0) byteDc = dc;
      sh = {sh[6:0], mosi};
      nbits = nbits + 1;
      if (nbits == 8) begin
        nbits = 0;
        bytesTotal = bytesTotal + 1;
        // a byte
        if (phase == 0) begin
          if (dc) begin
            if (nCmd != nInit) fail("data before the power-on commands are complete");
            phase = 1; nData = 1;
            if (sh != 0) fail("the blank frame is not black");
          end else begin
            if (nCmd >= nInit || sh != initCmds[nCmd]) begin
              $display("[tb] power-on command byte %0d: %02x", nCmd, sh);
              fail("a power-on command byte differs from the SSD1331 settings");
            end
            nCmd = nCmd + 1;
          end
        end else if (phase == 1) begin
          if (dc) begin
            nData = nData + 1;
            if (sh != 0) fail("the blank frame is not black");
          end else begin
            if (nData != 12288) fail("the blank frame is not 12288 bytes");
            if (sh != 8'hAF) fail("display on (AF) does not follow the blank frame");
            if (!vccen) fail("display on before VCCEN");
            phase = 2;
            $display("[tb] power-on: %0d command bytes as expected, blank frame of %0d bytes, display on", nCmd, nData);
          end
        end else if (phase == 3) begin
          if (!dc) begin
            if (rData != 0) fail("a command byte among the pixels");
            if (rCmd >= 6 || sh != window[rCmd]) fail("a refresh's window commands differ from 15 00 5F 75 00 3F");
            rCmd = rCmd + 1;
          end else begin
            if (rCmd != 6) fail("pixels before the window is set");
            if (rData[0] == 0) hiByte = sh;
            else begin
              pix = {hiByte, sh};
              if (pix[12:0] != rData / 2) begin
                if (errors < 5) $display("[tb] refresh %0d pixel %0d: %04x", refresh, rData / 2, pix);
                fail("a pixel arrived at the wrong position");
              end
              if (rData == 1) tagFirst = pix[15:13];
              framesSeen[pix[15:13]] = framesSeen[pix[15:13]] + 1;
            end
            rData = rData + 1;
          end
        end else fail("a byte after display on, outside a refresh");
      end
    end
    if (cs && sclk && !pSclk && phase >= 2) sclkWhileCsHigh = sclkWhileCsHigh + 1;
    if (!cs && pCs) begin
      // CS# falls
      if (phase >= 2) begin
        endRefresh;
        phase = 3; refresh = refresh + 1; rCmd = 0; rData = 0;
        for (j = 0; j < 8; j = j + 1) framesSeen[j] = 0;
      end
    end
    if (cs && !pCs) begin
      if (nbits != 0) fail("CS# raised within a byte");
    end
    if (front !== pFront) begin
      frontChanges = frontChanges + 1;
      // the bank may change only between refreshes: the step that lowers CS#
      if (!(phase == 3 && rCmd == 0 && rData == 0)) fail("the shown bank changed within a refresh");
    end
    pSclk = sclk; pMosi = mosi; pDc = dc; pCs = cs; pFront = front;
  end

  // the writer: one pixel a clock
  task drawFrame(input integer tag, input integer bank); integer i; begin
    for (i = 0; i < 6144; i = i + 1) begin
      @(posedge clk); #1;
      we = 1; wa = bank * 8192 + i; wd = tag * 8192 + i;
    end
    @(posedge clk); #1; we = 0;
  end endtask
  task setShow(input integer b); begin
    @(posedge clk); #1; cw = 1; cd = b;
    @(posedge clk); #1; cw = 0;
  end endtask
  task midRefresh(input integer r); begin
    while (!(refresh == r && rData >= 6000)) @(posedge clk);
  end endtask

  initial begin
    for (j = 0; j < 16; j = j + 1) begin torn[j] = 0; tagOf[j] = -1; whole[j] = 0; end
    for (j = 0; j < 8; j = j + 1) framesSeen[j] = 0;
    drawFrame(1, 0);
    // one buffer: frame 2 drawn while refresh 1 is half sent
    midRefresh(1); drawFrame(2, 0);
    // two buffers: draw into the bank not shown, then ask for it
    midRefresh(3); drawFrame(3, 1); setShow(1);
    midRefresh(4); drawFrame(4, 0); setShow(0);
    while (refresh < 6) @(posedge clk);   // (refresh 5 is checked when refresh 6 starts)
    $display("[tb] %0d bytes, %0d SCLK edges with CS# high, shown bank changed %0d times", bytesTotal, sclkWhileCsHigh, frontChanges);
    if (sclkWhileCsHigh != 0) fail("SCLK rose while CS# was high");
    if (!torn[1]) fail("one buffer: refresh 1 should show the artefact (torn)");
    if (torn[2] || tagOf[2] != 2) fail("one buffer: refresh 2 should be frame 2, whole");
    if (torn[3] || tagOf[3] != 2) fail("two buffers: refresh 3 should be frame 2, whole (frame 3 drawn into bank 1)");
    if (torn[4] || tagOf[4] != 3) fail("two buffers: refresh 4 should be frame 3, whole (bank 1)");
    if (torn[5] || tagOf[5] != 4) fail("two buffers: refresh 5 should be frame 4, whole (bank 0)");
    if (frontChanges != 2) fail("the shown bank should change twice");
    if (errors == 0) $display("PASS oled-sim (protocol, 6 refreshes; one buffer torn as on the board, two buffers whole)");
    else $display("FAIL oled-sim: %0d errors", errors);
    $finish;
  end
  initial begin
    #30000000;
    $display("FAIL oled-sim: timeout (refresh %0d, phase %0d)", refresh, phase);
    $finish;
  end
endmodule

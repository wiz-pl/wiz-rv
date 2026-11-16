# The PLIC per hart

golem's external-interrupt path (`src/Rv/Golem/Intc.wiz`, the 0x8000_2000 block), now
that the cores take interrupts (docs/csr.md).

## Design

* **One M-mode context per hart.** Context *h* is hart *h*'s (harts 0 … 3; there is no S
  mode, so no second context per hart). Each context has its own enable bitmap
  (`plicEnable + 4h`), threshold (`plicThreshold + 4h`) and claim/complete register
  (`plicClaim + 4h`). Hart *h*'s `mip.MEIP` is "context *h* has a pending, enabled
  source above its threshold" (`Intc.meip … h`), and only that: `Intc.mip s src h`
  drives hart *h*'s `In.irqE` (with its own CLINT MSIP/MTIP on `irqM`/`irqT`), in
  `Rv.Golem.Mini` (hart 0) and `Rv.Golem.Four` (each hart).
* **Sources.** 1 the UART receiver, 2/3/5/6 the mailboxes of harts 0/1/2/3 (a message
  is a level while it waits), 4 the spare external input. Every hart therefore has a
  source of its own, and any hart may also enable the shared ones (UART, spare) in its
  context. Priorities are per source (3 bits); 0 never interrupts.
* **Claim/complete is per context.** A claim returns the best pending enabled source of
  that context above its threshold (highest priority, lowest number on a tie), clears
  the shared pending bit and marks the source in service *for that context*; complete
  (a write of the source number) clears the service bit. Pending is shared, so a pulse
  is taken by the first context to claim it; a level source that stays high is pending
  again at once, and another context that also enables it could claim it while it is
  in service in the first (service bits are per context, unlike the standard PLIC's
  single claim). Nothing in golem enables one source in two contexts.
* **Finding the context.** A handler reads `mhartid` (CSR 0xf14, new: the hart's
  number, `coreStepHC h`) and claims at `0x80002080 + 4 × mhartid`. The MMIO hart-id
  word (`GMap.hartId`) and the read-only `MIP` MMIO word stay for software written
  before the CSRs.
* **Waiting.** A hart that has nothing to do sets `mie.MEIE` (and `mstatus.MIE`) and
  sleeps in WFI; it wakes when its own context has a source, and only then.

## The check

`tests/golem_plic_harts.wiz`: four real multi-cycle cores (each its own `mhartid`, its
own RAM with the same image) and the real `Intc`, each core's interrupt lines from its
own `Intc.mip`. Every hart installs a handler and sleeps in WFI; hart 0 sets the
mailbox sources' priorities, enables context *h* for source `mboxSrc h` only, and posts
messages 103/102/101/100 to harts 3/2/1/0. Each hart must take the external interrupt
(mcause 0x8000000b), claim its own source (2, 3, 5, 6) in its own context, read its own
message, complete, MRET and halt; nothing may stay pending. The cores' MMIO accesses of
one cycle are applied to the `Intc` in hart order (an interleaving `G4`'s shared port
can also produce); each core sees its `mip` from the state at the start of the cycle.

```
golem plic harts: 144 cycles; hart 0 [2 2147483659 2 100 0 ] hart 1 [2 2147483659 3 101 1 ]
hart 2 [2 2147483659 5 102 2 ] hart 3 [2 2147483659 6 103 3 ]; pending 0 — PASS
```

(per hart: halted cause 2 = EBREAK, mcause, claimed source, message, mhartid.)

## Not done

* `FProg.start` (the four-hart boot ROM) still wakes park harts by polling `MIP.MEIP`
  over MMIO rather than through a trap handler; converting it is a ROM change with no
  hardware change.
* The four-hart SoC itself (`G4`, with its bus, arbiter and caches) is not simulated
  with real cores in a test (its netlist simulation is over the test budget; see
  tests/golem_four.wiz); the test above uses the same `Intc` and the same per-hart
  `mip` wiring with a simpler MMIO interleaving.
* No S-mode contexts, no PLIC gateway edge mode, and the "claimed by one context
  only" rule of the standard PLIC (see above).

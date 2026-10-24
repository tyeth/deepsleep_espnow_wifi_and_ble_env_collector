# Controller power verification deployed

The power-cycle fix from [controller PR 2](https://github.com/tyeth-ai-assisted/sbc-mcu-dut-controller/pull/2)
is now installed in the running controller. The deployed adapter hash is
`b54450c92231f4cb30a4e7d0200689ab81a5a0581995c5a4b18f8cf2b59cc982`, exactly
matching public candidate `6ca2f2dffa7dcc6ea0094744f77433f13e7aa278` and the
earlier [physical C6 check](controller-c6-physical-2026-10-23.md).

The live adapter matched the candidate's unchanged parent exactly. The two-file
patch applied cleanly to an isolated copy of the live revision. All 61 focused
bridge/client/host tests, Ruff and module mypy checks passed there. An initial
attempt inherited production settings: one API test returned 401, and Ruff was
absent from the runtime environment. That failed run is retained. The successful
retest removed production HIL settings, disabled live topology, and placed lint
tools only in the temporary validation directory.

The cutover waited for queued and active jobs plus unreleased leases to clear,
checked the independent soak gate, then held a SQLite admission lock while
rechecking idle state and stopping the service. It changed only the reviewed
adapter and its regression tests. Six guard controls covered concurrent job
admission, each active job state, unreleased leases, concurrent source changes,
stop failure and failed-readiness rollback. They passed on Windows and Linux.

The independent deployment unit exited successfully. The restarted controller
reported database readiness, a new process, the expected source hash and a
clean tracked checkout. A fresh API job then completed successfully. No rollback
was needed; original files and failed-run evidence remain privately retained.

This closes the **service deployment** gap. The earlier physical test remains
one C6 cycle on one hub chain; no additional physical cycle or electrical rail
measurement is claimed for this deployment. The fix rejects transport outages
as proof of disappearance and requires observed off/absent and on/enabled/present
states before a cold boot can pass. Endpoint-capacity scheduling and stale
USB/IP recovery remain open under controller issue 1.

[Sanitized deployment evidence](controller-power-deployment-2026-10-23.json).

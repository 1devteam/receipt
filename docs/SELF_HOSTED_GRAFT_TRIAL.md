# Receipt internal G.R.A.F.T.+ self-hosted trial

This trial exercises the internal stock graph against Receipt itself rather than only a synthetic fixture.

The repository checkout is collected through Receipt's normal collector and then passed directly into `build_stock_graph()`.

The smoke contract requires that the resulting artifact:

- uses `receipt.graft.stock.v1`;
- contains at least twenty Python source nodes;
- contains real internal relationships and symbols;
- includes known core stock such as `compiler/compile.py` and `receipt_cli/stack.py`;
- keeps `outcome_authority=not-determined`;
- keeps `grants_execution_authority=false`;
- contains no machine-local source origin in any graph node.

The purpose is to prove that Receipt can reconstruct its own actual stock end to end without relying on a hand-authored graph fixture.

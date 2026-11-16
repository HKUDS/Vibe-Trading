import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { ResearchLab } from "../ResearchLab";

const mock = vi.hoisted(() => ({getResearchLabCatalog:vi.fn(),startResearchLabJob:vi.fn(),getResearchLabJob:vi.fn()}));
vi.mock("@/lib/api",()=>({api:mock}));
const catalog={runs:[{id:"baseline",codes:["AAPL.US"],start_date:"2026-01-01",end_date:"2026-06-01",has_prices:true,has_trace:false,parameters:{fast:10,slow:40}},
  {id:"research-run",codes:[],has_prices:false,has_trace:true,parameters:{}}],
  cases:[{id:"research.window_boundary.v1",prompt:"Keep this task prompt unchanged.",scenario:"backtest_validation",checks:[]}]};

beforeEach(()=>{
  Object.values(mock).forEach(fn=>fn.mockReset());history.replaceState(null,"","/");
  mock.getResearchLabCatalog.mockResolvedValue(catalog);
  mock.startResearchLabJob.mockResolvedValue({id:"job1",action:"factor_audit",status:"completed",result:{kind:"factor_audit",count:1,finding_count:0,rows:[{id:"gtja191_149",minimum_bars:253,policy:"conditional_sample",valid:true}]}});
});

it("submits real cost scenarios from a saved baseline",async()=>{
  render(<ResearchLab/>,{wrapper:MemoryRouter});
  await screen.findByRole("option",{name:/AAPL.US/});
  fireEvent.change(screen.getByLabelText("Trading fee multipliers"),{target:{value:"1, 3"}});
  fireEvent.change(screen.getByLabelText("Extra slippage (bp)"),{target:{value:"0, 10"}});
  fireEvent.click(screen.getByRole("button",{name:"Run study"}));
  await waitFor(()=>expect(mock.startResearchLabJob).toHaveBeenCalledWith("cost_sensitivity",{run_dir:"baseline",scenarios:[
    {name:"1× / 0 bp",fee_multiplier:1,extra_slippage_bps:0},{name:"1× / 10 bp",fee_multiplier:1,extra_slippage_bps:10},
    {name:"3× / 0 bp",fee_multiplier:3,extra_slippage_bps:0},{name:"3× / 10 bp",fee_multiplier:3,extra_slippage_bps:10}]}));
});

it("exposes training objective and windows with bounded constructor choices",async()=>{
  render(<ResearchLab/>,{wrapper:MemoryRouter});await screen.findByRole("option",{name:/AAPL.US/});
  fireEvent.click(screen.getByRole("tab",{name:"Out-of-sample testing"}));
  fireEvent.change(screen.getByLabelText("fast · Parameter choices"),{target:{value:"10,20"}});
  fireEvent.change(screen.getByLabelText("Training objective"),{target:{value:"total_return"}});
  fireEvent.change(screen.getByLabelText("Training window"),{target:{value:"expanding"}});
  fireEvent.click(screen.getByRole("button",{name:"Run study"}));
  await waitFor(()=>expect(mock.startResearchLabJob).toHaveBeenCalledWith("walk_forward",expect.objectContaining({objective:"total_return",training:"expanding",holdout_bars:20,
    candidates:[{name:"candidate-1",parameters:{fast:10,slow:40}},{name:"candidate-2",parameters:{fast:20,slow:40}}]})));
});

it("replays actual trace runs and keeps the selected task prompt",async()=>{
  render(<ResearchLab/>,{wrapper:MemoryRouter});await screen.findByRole("option",{name:/AAPL.US/});
  fireEvent.click(screen.getByRole("tab",{name:"Task replay"}));
  expect(screen.getByText("Keep this task prompt unchanged.")).toBeInTheDocument();
  expect(screen.getByLabelText("Saved run")).toHaveValue("research-run");
  fireEvent.click(screen.getByRole("button",{name:"Run study"}));
  await waitFor(()=>expect(mock.startResearchLabJob).toHaveBeenCalledWith("replay",{run_dir:"research-run",case_ids:["research.window_boundary.v1"]}));
});

it("recovers the job's action and report after reload",async()=>{
  history.replaceState(null,"","/?job=saved");
  mock.getResearchLabJob.mockResolvedValue({id:"saved",action:"factor_audit",status:"completed",result:{kind:"factor_audit",count:1,finding_count:0,rows:[{id:"gtja191_149",minimum_bars:253,policy:"conditional_sample",valid:true}]}});
  render(<ResearchLab/>,{wrapper:MemoryRouter});
  expect(await screen.findByText("gtja191_149")).toBeInTheDocument();
  expect(screen.getByRole("tab",{name:"Factor contracts"})).toHaveAttribute("aria-selected","true");
});

it("refuses coercing booleans into fee multipliers",async()=>{
  render(<ResearchLab/>,{wrapper:MemoryRouter});await screen.findByRole("option",{name:/AAPL.US/});
  fireEvent.change(screen.getByLabelText("Trading fee multipliers"),{target:{value:"true"}});
  fireEvent.click(screen.getByRole("button",{name:"Run study"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("Enter finite numeric choices.");
  expect(mock.startResearchLabJob).not.toHaveBeenCalled();
});


it("restores the replay's original run and case alongside its report", async()=>{
  history.replaceState(null,"","/?job=replay");
  mock.getResearchLabJob.mockResolvedValue({id:"replay",action:"replay",status:"completed",request:{run_dir:"research-run",case_ids:["research.window_boundary.v1"]},
    result:{kind:"replay",evaluation_status:"passed",summary:{evaluation_coverage:1},reports:[]}});
  render(<ResearchLab/>,{wrapper:MemoryRouter});
  await screen.findByText("Saved run: research-run");
  expect(screen.getByLabelText("Saved run")).toHaveValue("research-run");
  expect(screen.getByLabelText("Evaluation task")).toHaveValue("research.window_boundary.v1");
});


it("localizes an empty parameter choice", async()=>{
  render(<ResearchLab/>,{wrapper:MemoryRouter}); await screen.findByRole("option",{name:/AAPL.US/});
  fireEvent.change(screen.getByLabelText("Trading fee multipliers"),{target:{value:"1,,2"}});
  fireEvent.click(screen.getByRole("button",{name:"Run study"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("Enter a value for every choice.");
  expect(mock.startResearchLabJob).not.toHaveBeenCalled();
});

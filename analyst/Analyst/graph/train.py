import json
import time
from pathlib import Path
import pandas as pd
from langchain_openai import ChatOpenAI
from graph.graph_workflow import TextGradTraderWorkflow
from agent import *
from graph.init_state import init_state
from config import get_chat_openai_kwargs
from services.module_io_dispatcher import ModuleIODispatcher, ModuleSnapshot
from services.pipeline_coordinator import AnalysisPipelineCoordinator
from services.pipeline_coordinator import split_serial_nodes


class TextGradTraderRunner():
    def __init__(self,
                 config,
                 symbol,
                 model,
                 task_id=None,
                 module_output_root=None,
                 on_module_event=None,
                 ):
        self.config = config
        self.symbol = symbol
        self.model = model
        self.task_id = task_id or f"{symbol}-{model}"
        self.module_output_root = module_output_root or self.config.get("result", "./result")
        self.on_module_event = on_module_event
        llm_kwargs = get_chat_openai_kwargs(config)
        self.deep_think_llm = ChatOpenAI(
            model=config["deep_think_llm"],
            temperature=1,
            max_tokens=4096,
            **llm_kwargs,
        )
        self.quick_think_llm = ChatOpenAI(
            model=config["quick_think_llm"],
            temperature=1,
            max_tokens=4096,
            **llm_kwargs,
        )
        cache_root = self.config.get("data_cache", "./data_cache")
        self.router_memory = FinancialSituationMemory("router_memory", f"{cache_root}/{self.symbol}/{self.model}/router_memory")
        self.manager_memory = FinancialSituationMemory("manager_memory", f"{cache_root}/{self.symbol}/{self.model}/manager_memory")
        self.risk_memory = FinancialSituationMemory("risk_memory", f"{cache_root}/{self.symbol}/{self.model}/risk_memory")
        self.final_memory = FinancialSituationMemory("final_memory", f"{cache_root}/{self.symbol}/{self.model}/final_memory")
        self.graph_setup = TextGradTraderWorkflow(self.quick_think_llm, self.deep_think_llm, self.router_memory, self.manager_memory, self.risk_memory, self.final_memory)
        self.log_states_dict = {}

    def run(self, date, cash, day_count):
        main_state, postprocess = self.run_main(date, cash, day_count)
        return postprocess(main_state)

    def run_main(self, date, cash, day_count):
        init_agent_state = init_state(self.symbol, date, cash, day_count, self.model)
        analyst_nodes, owners, serial_nodes = self.graph_setup.build_node_registry()
        main_nodes, postprocessing_nodes = split_serial_nodes(serial_nodes)
        dispatcher = ModuleIODispatcher(
            output_root=self.module_output_root,
            task_id=self.task_id,
            on_event=self.on_module_event,
        )

        def persist_module(name, delta, state):
            if not delta:
                return
            dispatcher.submit(ModuleSnapshot(name, delta, time.time()))

        coordinator = AnalysisPipelineCoordinator(
            analyst_nodes=analyst_nodes,
            analyst_field_owners=owners,
            serial_nodes=main_nodes,
            on_module_result=persist_module,
        )
        try:
            main_state = coordinator.run(init_agent_state)
        finally:
            dispatcher.close()
        frozen_state = dict(main_state)

        def postprocess(state=None):
            return self.run_postprocessing(state or frozen_state, postprocessing_nodes)

        return frozen_state, postprocess

    def run_postprocessing(self, state, serial_nodes=None):
        if serial_nodes is None:
            _, _, all_serial_nodes = self.graph_setup.build_node_registry()
            _, serial_nodes = split_serial_nodes(all_serial_nodes)
        coordinator = AnalysisPipelineCoordinator(
            analyst_nodes={},
            analyst_field_owners={},
            serial_nodes=serial_nodes,
        )
        return coordinator.run(dict(state))

    def _log_state(self, date, final_state):
        self.log_states_dict[str(date)] = {
            "company_of_interest": str(final_state.get("symbol", "")),
            "trade_date": str(final_state.get("trade_date", "")),
            "market_report": str(final_state.get("market_report", "")),
            "news_report": str(final_state.get("news_report", "")),
            "fundamentals_report": str(final_state.get("fundamentals_report", "")),
            "industry_report": str(final_state.get("industry_report", "")),
            "momentum_report": str(final_state.get("momentum_report", "")),
            "router_report": str(final_state.get("router", "")),
            "investment_plan": str(final_state.get("investment_plan", "")),
            "risk_plan": str(final_state.get("risk_plan", "")),
            "final_decision": str(final_state.get("final_decision", "")),

            "learned_beliefs": str(final_state.get("learned_beliefs", "")),
            "weekly_summary": str(final_state.get("weekly_summary", "")),
            "actual_outcome": str(final_state.get("actual_outcome", "")),
            "cash": float(final_state.get("cash", 0.0)),
        }
        directory = Path(f"eval_results/{self.symbol}/logs/{self.model}")
        directory.mkdir(parents=True, exist_ok=True)

        with open(
                f"eval_results/{self.symbol}/logs/{self.model}/full_states_log_{date}.json",
                "w",
                encoding="utf-8",
        ) as f:
            json.dump(self.log_states_dict, f, indent=4, ensure_ascii=False)





train_model = TextGradTraderRunner


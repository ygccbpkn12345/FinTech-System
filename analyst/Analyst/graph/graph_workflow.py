from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
from agent import *
from graph.node_utils import wrap_node

ANALYST_NODES = [
    "market_analyst",
    "news_analyst",
    "fundamentals_analyst",
    "industry_analyst",
    "momentum_analyst",
]


def fan_out_analysts(state):
    """显式 fan-out：5 个分析师并行，各写独立 report 字段。"""
    return [Send(node_name, state) for node_name in ANALYST_NODES]


class TextGradTraderWorkflow:
    def __init__(
        self,
        quick_thinking_llm: ChatOpenAI,
        deep_thinking_llm: ChatOpenAI,
        router_memory,
        manager_memory,
        risk_memory,
        final_memory,
    ):
        self.quick_thinking_llm = quick_thinking_llm
        self.deep_thinking_llm = deep_thinking_llm
        self.router_memory = router_memory
        self.manager_memory = manager_memory
        self.risk_memory = risk_memory
        self.final_memory = final_memory

    def build_node_registry(self):
        """Build explicit nodes for the threaded fan-out/fan-in coordinator."""
        analyst_node = AnalystNode(self.quick_thinking_llm)
        analyst_nodes = {
            "market_analyst": wrap_node("market_analyst", analyst_node.create_market_analyst_node()),
            "news_analyst": wrap_node("news_analyst", analyst_node.create_news_analyst_node()),
            "fundamentals_analyst": wrap_node(
                "fundamentals_analyst", analyst_node.create_fundamentals_analyst_node()
            ),
            "industry_analyst": wrap_node(
                "industry_analyst", analyst_node.create_industry_analyst_node()
            ),
            "momentum_analyst": wrap_node(
                "momentum_analyst", analyst_node.create_momentum_analyst_node()
            ),
        }
        analyst_field_owners = {
            "market_analyst": {"market_report"},
            "news_analyst": {"news_report"},
            "fundamentals_analyst": {"fundamentals_report"},
            "industry_analyst": {"industry_report"},
            "momentum_analyst": {"momentum_report"},
        }
        reflection = wrap_node(
            "reflector",
            create_semantic_gradient_descent_reflection(
                self.quick_thinking_llm,
                [self.router_memory, self.manager_memory, self.risk_memory, self.final_memory],
            ),
        )
        weekly_reflection = wrap_node(
            "weekly_reflector",
            create_weekly_strategy_distillation_node(
                self.quick_thinking_llm,
                [self.manager_memory, self.risk_memory, self.final_memory],
            ),
        )

        def optional_weekly_reflection(state):
            if check_weekly_trigger(state) == "weekly_reflector":
                return weekly_reflection(state)
            return {}

        serial_nodes = [
            (
                "router",
                wrap_node(
                    "router",
                    create_bayesian_contextual_gating_router(
                        self.quick_thinking_llm, self.router_memory
                    ),
                ),
            ),
            (
                "manager",
                wrap_node(
                    "manager",
                    create_adversarial_pareto_reasoning_manager(
                        self.deep_thinking_llm, self.manager_memory
                    ),
                ),
            ),
            (
                "risk_manager",
                wrap_node(
                    "risk_manager",
                    create_risk_manager(self.deep_thinking_llm, self.risk_memory),
                ),
            ),
            (
                "final_decision",
                wrap_node(
                    "final_decision",
                    create_final_manager(self.deep_thinking_llm, self.final_memory),
                ),
            ),
            ("environment_simulation", wrap_node("environment_simulation", execution_simulation_node)),
            ("reflector", reflection),
            ("weekly_reflector", optional_weekly_reflection),
        ]
        return analyst_nodes, analyst_field_owners, serial_nodes

    def setup_graph(self):
        analyst_node = AnalystNode(self.quick_thinking_llm)
        market_analyst = wrap_node(
            "market_analyst",
            analyst_node.create_market_analyst_node(),
            limit_analyst_concurrency=True,
        )
        news_analyst = wrap_node(
            "news_analyst",
            analyst_node.create_news_analyst_node(),
            limit_analyst_concurrency=True,
        )
        fundamentals_analyst = wrap_node(
            "fundamentals_analyst",
            analyst_node.create_fundamentals_analyst_node(),
            limit_analyst_concurrency=True,
        )
        industry_analyst = wrap_node(
            "industry_analyst",
            analyst_node.create_industry_analyst_node(),
            limit_analyst_concurrency=True,
        )
        momentum_analyst = wrap_node(
            "momentum_analyst",
            analyst_node.create_momentum_analyst_node(),
            limit_analyst_concurrency=True,
        )

        router = wrap_node(
            "router",
            create_bayesian_contextual_gating_router(self.quick_thinking_llm, self.router_memory),
        )
        manager = wrap_node(
            "manager",
            create_adversarial_pareto_reasoning_manager(self.deep_thinking_llm, self.manager_memory),
        )
        risk_manager = wrap_node(
            "risk_manager",
            create_risk_manager(self.deep_thinking_llm, self.risk_memory),
        )
        final_manager = wrap_node(
            "final_decision",
            create_final_manager(self.deep_thinking_llm, self.final_memory),
        )
        environment_simulation = wrap_node(
            "environment_simulation",
            execution_simulation_node,
        )
        reflection = wrap_node(
            "reflector",
            create_semantic_gradient_descent_reflection(self.quick_thinking_llm, [self.router_memory, self.manager_memory, self.risk_memory, self.final_memory]),
        )
        weekly_reflection = wrap_node(
            "weekly_reflector",
            create_weekly_strategy_distillation_node(
                self.quick_thinking_llm,
                [self.manager_memory, self.risk_memory, self.final_memory],
            ),
        )

        workflow = StateGraph(AgentState)
        workflow.add_node("market_analyst", market_analyst)
        workflow.add_node("news_analyst", news_analyst)
        workflow.add_node("fundamentals_analyst", fundamentals_analyst)
        workflow.add_node("industry_analyst", industry_analyst)
        workflow.add_node("momentum_analyst", momentum_analyst)
        workflow.add_node("router", router)
        workflow.add_node("manager", manager)
        workflow.add_node("risk_manager", risk_manager)
        workflow.add_node("final_decision", final_manager)
        workflow.add_node("environment_simulation", environment_simulation)
        workflow.add_node("reflector", reflection)
        workflow.add_node("weekly_reflector", weekly_reflection)

        workflow.add_conditional_edges(START, fan_out_analysts, ANALYST_NODES)

        for analyst in ANALYST_NODES:
            workflow.add_edge(analyst, "router")

        workflow.add_edge("router", "manager")
        workflow.add_edge("manager", "risk_manager")
        workflow.add_edge("risk_manager", "final_decision")
        workflow.add_edge("final_decision", "environment_simulation")
        workflow.add_edge("environment_simulation", "reflector")
        workflow.add_conditional_edges(
            "reflector",
            check_weekly_trigger,
            {
                "weekly_reflector": "weekly_reflector",
                END: END,
            },
        )
        workflow.add_edge("weekly_reflector", END)
        return workflow.compile()


graph_workflow = TextGradTraderWorkflow


def check_weekly_trigger(state) -> str:
    day = state.get("day_count", 0)
    if day > 0 and day % 7 == 0:
        return "weekly_reflector"
    else:
        return END

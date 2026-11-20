"""算法管理 HTTP 接口，与聊天共享同一个 AlgorithmManager。"""

from fastapi import APIRouter, HTTPException, Response

from services.algorithm_manager import AlgorithmDefinition, AlgorithmManager, DuplicateAlgorithmError


def build_algorithm_router(manager: AlgorithmManager) -> APIRouter:
    router = APIRouter(prefix="/api/algorithms", tags=["algorithms"])

    def perform(operation, *args):
        try:
            return operation(*args)
        except KeyError as exc:
            raise HTTPException(404, "算法不存在") from exc
        except DuplicateAlgorithmError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(503, "算法配置保存失败，请检查服务端存储后重试") from exc

    @router.get("")
    def list_algorithms():
        return {"items": manager.list()}

    # 固定路径必须声明在 /{name} 前面。
    @router.get("/local-tools")
    def list_local_tools():
        return {"items": manager.available_local_tools()}

    @router.post("", status_code=201)
    def create_algorithm(request: AlgorithmDefinition):
        return perform(manager.create, request.model_dump())

    @router.get("/{name}")
    def get_algorithm(name: str):
        return perform(manager.get, name)

    @router.put("/{name}")
    def update_algorithm(name: str, request: AlgorithmDefinition):
        return perform(manager.update, name, request.model_dump())

    @router.delete("/{name}", status_code=204)
    def delete_algorithm(name: str):
        perform(manager.delete, name)
        return Response(status_code=204)

    return router

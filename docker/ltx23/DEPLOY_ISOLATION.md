# LTX-2.3 新部署隔离说明

LTX-2.3 部署与线上 LTX-2 环境完全隔离，互不影响。

## 隔离策略

| 资源 | 线上 LTX-2（不动） | LTX-2.3 新部署 |
|------|-------------------|----------------|
| **Endpoint** | `42qdgmzjc9ldy5` | 新建，得到新 ID |
| **Docker 镜像** | `nooka210/ltx2-comfyui-worker:v62` | `nooka210/ltx23-worker:v1` |
| **Network Volume** | 线上在用 | 新建，不与线上共用 |

## Step 6: 构建与推送

```bash
cd zzh/dl-ait2v/docker/ltx23
./build_and_push.sh
```

或手动执行：

```bash
cd zzh/dl-ait2v/docker
docker build --platform linux/amd64 -f ltx23/Dockerfile -t nooka210/ltx23-worker:v1 .
docker push nooka210/ltx23-worker:v1
```

## 创建新 Endpoint 时

1. **Docker Image** 填：`nooka210/ltx23-worker:v1`
2. **Network Volume** 选新建的，不要选线上在用的
3. 创建后得到新的 Endpoint ID，用于测试

线上 `42qdgmzjc9ldy5` 继续使用 v62 镜像，不受任何影响。

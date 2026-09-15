# Validação do MVP

Executada em 14/09/2026, Windows, Python **3.11.11**.

| Verificação | Resultado |
| --- | --- |
| Suíte completa | **265 testes aprovados** |
| Parser, decisão, identificadores e modelos do núcleo | **100% de linhas e ramos**, 338 instruções e 120 ramos |
| HTTP e dependências | Autenticação, contratos, limites, privacidade e adaptação de erros testados |
| Pipeline live com transporte externo mockado | Gemini seguido de BrasilAPI; sucesso/404/429/503; sem fallback para demo |
| API em processo local, nove requisições reais | Todos os status/scores correspondem ao manifesto |
| Navegador Edge via Playwright | DANGER/60 e SAFE/0; desktop e mobile; sem erro JavaScript ou overflow horizontal |
| Ruff | Verificação concluída sem erros |
| Pacote Python wheel | Construído e instalado em ambiente separado a partir de requirements.lock |
| Pacote instalado fora de src | Endpoint SAFE, catálogos, fixtures e assets web carregados corretamente |

Comandos principais usados:

```powershell
.\.tools\test-env\Scripts\python.exe -m pytest --tb=short
.\.tools\test-env\Scripts\ruff.exe check src tests scripts run.py
.\.tools\test-env\Scripts\python.exe scripts\check_demo.py
```

Os ambientes `.tools/` e `.venv/` são locais, ignorados pelo Git. Para reprodução em outra máquina, seguir o README. A suíte emite dois avisos de depreciação nas dependências de TestClient/AnyIO; não houve falhas de teste.

## Limites do que foi verificado

- **Docker não estava instalado neste ambiente**. Dockerfile e Compose foram preparados; não foi executado build/start do container. A execução funcional foi validada diretamente em Python e por instalação do wheel.
- Nenhuma credencial real Gemini foi fornecida, portanto não houve chamada paga ou medição de leitura real. Contratos e falhas foram exercitados com HTTP mockado.
- Não foi realizado teste de carga de produção, calibração de risco ou validação de OCR com documentos de clientes.
- Não houve publicação em nuvem, criação de repositório remoto ou gravação de pitch. Os materiais técnicos estão prontos para a equipe publicar após configurar seus acessos.

Este documento descreve a validação final do MVP.

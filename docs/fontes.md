# Referências técnicas do núcleo

Consultadas em 14/09/2026. Não há consulta dessas fontes na execução dos testes ou do motor.

| Tema | Fonte | Uso |
| --- | --- | --- |
| Cobrança, DVs e ciclo de 2025 | [Manual oficial Sicredi, seção Boletos](https://developers.sicredi.com.br/public/docs/getting-started-cnabs-240-billing) | Layout 44/47, módulo 10 nos campos, módulo 11 geral, fator 1000 em 22/02/2025 |
| Vetor publicado de cobrança | [Manual do Banco do Brasil, janeiro/2016, cópia hospedada pela Sysala](https://www.sysala.com.br/arquivos/downloads/manual_boleto/BB/MontarBoleto.pdf) | Linha de exemplo do formulário: `00190.50095 40144.816069 06809.350314 3 37370000000100`, valor nominal R$ 1,00; referência histórica para estrutura e DVs, não para o ciclo vigente |
| CNPJ alfanumérico | [Manual Receita/Serpro](https://www.gov.br/receitafederal/pt-br/centrais-de-conteudo/publicacoes/documentos-tecnicos/cnpj/manual-dv-cnpj.pdf) | ASCII menos 48 e módulo 11; exemplo publicado `12.ABC.345/01DE-35` |
| Formato de arrecadação | [Catálogo FEBRABAN](https://portal.febraban.org.br/pagina/3425/33/pt-br/layout-febraban) | Especificação separada, fora do MVP |
| Códigos bancários | [Rede arrecadadora — Receita Federal](https://www.gov.br/receitafederal/pt-br/assuntos/orientacao-tributaria/pagamentos-e-parcelamentos/rede-arrecadadora-de-receitas-federais-bancos) | Catálogo parcial versionado com aliases de apresentação |
| Estados cadastrais | [Contrato CNPJ da BrasilAPI](https://raw.githubusercontent.com/BrasilAPI/BrasilAPI/main/pages/docs/doc/cnpj.json) | Campos e códigos tipados; 404 significa não encontrado na base consultada |

Os arquivos em `src/scamshield/data/config/` incluem suas fontes específicas. As fontes de instituições comprovam a identidade cadastral e sua natureza; não comprovam que qualquer boleto em seu nome seja legítimo ou que exista vínculo com um seller específico.

Os demais vetores de boleto são sintéticos. O helper dos testes calcula DVs independentemente das funções de produção; o vetor publicado fixa também a ordem dos campos e os três DVs. Cadastros de teste são simulados e não representam consultas reais ou avaliações de risco das instituições citadas.

## Integrações e retenção

- [Gemini generateContent REST](https://ai.google.dev/api/generate-content): endpoint, inlineData, cabeçalho de autenticação, resposta de candidatos, configuração estruturada e store.
- [Documentos PDF no Gemini](https://ai.google.dev/gemini-api/docs/document-processing) e [imagens](https://ai.google.dev/gemini-api/docs/image-understanding): formatos de entrada multimodal.
- [Saída estruturada](https://ai.google.dev/gemini-api/docs/structured-output): esquema JSON para extração, validado novamente pelo serviço.
- [Termos do Gemini](https://ai.google.dev/gemini-api/terms): retenção/uso externo não são eliminados pelo descarte local.
- [Upload no FastAPI](https://fastapi.tiangolo.com/tutorial/request-files/): UploadFile pode passar de RAM para disco; por isso este MVP recebe base64 em JSON limitado.

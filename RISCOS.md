# Riscos conhecidos do MVP

| Risco | Tratamento atual | Limitação restante |
| --- | --- | --- |
| Falso positivo | Nome diferente/intermediário geram WARNING; aliases/fuzzy e comparação nominal | Limiar não calibrado; leitura pode errar |
| Falso negativo | DVs e cruzamentos explícitos | CNPJ copiado e campo livre alterado podem continuar consistentes; sem autenticação do recebedor |
| Fontes gratuitas | Timeout, cooldown de 429, erros tipados e WARNING | Sem SLA, cadastro incompleto/defasado; comercial precisa de fonte contratada |
| Ausência de histórico | Régua determinística auditável | Sem reputação ou vínculo comercial comprovado |
| Latência | Orçamento de 4,5 s, timeouts e cancelamento | Cadastro depende da leitura; meta não validada com carga/credenciais reais; inspeção PDF local é síncrona |
| Privacidade | Upload em memória, logs mínimos e cache cadastral só na requisição | Heap não tem apagamento físico garantido; retenção externa/proxy depende da implantação |
| Escala | Limites de arquivo, simultaneidade e taxa | Um worker; limites locais; documentos patológicos exigem isolamento adicional em produção |
| Demo | Nove fixtures pelo mesmo motor | Fake identifica arquivos exatos; não mede qualidade do OCR nem eficácia antifraude |
| Catálogos | Fontes versionadas, ausência gera WARNING | Catálogo parcial e manutenção manual |

SAFE não garante autenticidade. DANGER indica incompatibilidade relevante, não prova de intenção fraudulenta. O parceiro mantém a decisão sobre pagamento.

Áudio, QR PIX, links/VirusTotal, boleto registrado, mTLS e OAuth2 não estão implementados.

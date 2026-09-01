# Operação

Guia para instalar, configurar, testar e operar o K4binho Promo Bot.

## 1. Instalação

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

O Mercado Livre usa **Google Chrome visível** com perfil persistente.

## 2. Configuração

Copie:

```bash
copy .env.example .env
```

ou no shell Unix:

```bash
cp .env.example .env
```

Preencha Telegram, Mercado Livre, AliExpress e as fontes que estiverem ativas.

### Configuração comercial principal

| Variável | Padrão | Função |
|---|---:|---|
| `SCORE_MIN` | 70 | Score mínimo normal do ML. |
| `LAUNCH_SCORE` | 95 | Publica oferta forte antes do histórico mínimo. |
| `PRICE_MIN` | 30 | Evidência mínima de preço. |
| `MIN_HISTORY_OBS` | 4 | Observações para histórico maduro. |
| `MAX_POSTS_PER_CYCLE` | 5 no `.env.example` | Limite ML por ciclo. |
| `POLL_INTERVAL_SECONDS` | 900 no `.env.example` | Intervalo entre ciclos. |

## 3. Promotion Engine V1

Copie o exemplo:

```bash
copy promotions.example.json promotions.json
```

`promotions.json` é configuração operacional e fica fora do Git/export sanitizado.

### Mercado Livre — descoberta automática

```env
PROMOTIONS_FILE=promotions.json
ML_COUPON_DISCOVERY_ENABLED=true
ML_COUPON_SCAN_ITEMS=8
ML_COUPON_CACHE_HOURS=6
```

Fluxo:

1. coleta ofertas normalmente;
2. escolhe uma pequena amostra de produtos fortes ainda sem cache;
3. abre as páginas no Chrome logado;
4. procura texto de cupom/desconto;
5. guarda o resultado em `promotion_cache.json`;
6. calcula preço efetivo;
7. refaz o score com o cupom confirmado.

O histórico em `price_history.json` continua guardando o **preço listado**, não o preço temporário com cupom.

No log:

```text
[ML] ... | Promocao: 8 | Codigos: 3 | Scaneados: 8 | ...
[ML][cupom VANTAGEMJA] published: score 84 | 2299.00 -> 2113.00 | RTX 5060...
```

Se o Chrome estiver pesado, reduza `ML_COUPON_SCAN_ITEMS` para 4–6. Não aumente muito sem medir duração do ciclo.

### Promoções manuais / AliExpress

Em `promotions.json`, uma regra pode ser:

```json
{
  "enabled": true,
  "kind": "coupon",
  "code": "CODIGO",
  "discount_amount": 140,
  "minimum_spend": 1200,
  "starts_at": "2026-09-01T00:00:00-03:00",
  "expires_at": "2026-09-05T23:59:59-03:00"
}
```

O motor escolhe automaticamente o maior desconto válido para o preço do produto.

Para restringir a produtos específicos:

```json
"match_keywords": ["rtx", "monitor", "ryzen"]
```

### Promoções condicionais

Campos suportados:

```json
"selected_users_only": true,
"app_only": true,
"requires_coins": true
```

Essas condições podem aparecer no Telegram, mas **não reduzem o preço usado no score**, porque não são universais.

### Página de resgate da Shopee

Estrutura já suportada:

```json
{
  "kind": "coupon_rescue",
  "rescue_url": "https://s.shopee.com.br/...",
  "description": "Resgate os cupons antes da compra"
}
```

A Shopee ainda não possui ciclo de postagem ativo.

## 4. Avisos de campanhas

`promotions.json` pode conter `campaigns` com `starts_at` e `notice_hours_before`.

```env
PROMOTION_CAMPAIGN_NOTICES_ENABLED=true
```

O bot envia o aviso apenas uma vez e registra em `promotion_state.json`.

Use isso para eventos como campanha de meia-noite. Não cadastre evento sem confirmação de horário/códigos.

## 5. Login do Mercado Livre

```bash
python login_ml.py
```

A sessão fica em `ml_profile/`.

## 6. Testes

Suite completa:

```bash
python -m pytest -q
```

Estado desta versão: **104 passed**.

Validação de sintaxe:

```bash
python -m compileall -q .
```

## 7. Dry-run

```bash
python bot.py --once --dry-run
```

O dry-run:

- não posta;
- não abre Chrome para nova descoberta de cupons;
- usa cupons manuais de `promotions.json` e cache já existente;
- mostra score e motivos;
- mostra preço efetivo quando houver promoção conhecida.

## 8. Ciclo real

```bash
python bot.py --once
```

O Chrome pode abrir em dois momentos no ciclo ML:

1. descoberta limitada de cupons sem cache;
2. geração dos links de afiliado dos itens selecionados.

O cache reduz a repetição do primeiro passo.

## 9. Loop contínuo

```bash
python bot.py
```

No Windows, mantenha o launcher atual:

```text
run_bot.bat → python -u bot.py >> bot.log 2>&1
```

Acompanhar log no PowerShell:

```powershell
Get-Content .\bot.log -Wait -Tail 50
```

## 10. Segurança de logs

O projeto agora coloca `httpx` e `httpcore` em nível WARNING para evitar registrar todas as URLs de requisição com tokens/chaves.

Isso **não revoga credenciais já expostas em logs antigos**. Se um token/chave apareceu em arquivo compartilhado, rotacione.

## 11. Export seguro

Nunca compacte manualmente a pasta inteira. Rode:

```bash
python export_project.py
```

O export exclui:

- `.env`;
- `ml_token.json`;
- `ml_profile/`;
- `bot.log`;
- estados JSON operacionais;
- cache de promoções;
- `promotions.json`;
- qualquer `.zip` antigo dentro do projeto.

## 12. Diagnóstico rápido

| Sintoma | Verificar |
|---|---|
| Poucas ofertas ML | Linha de funil `[ML] Encontrados ... Selecionados`. |
| Cupom conhecido não aparece | Se anúncio entrou no scan/cache e se cupom está visível para sua conta. |
| Chrome abre demais | Reduzir scan ou aumentar cache. |
| Preço condicional não entra no score | Comportamento intencional por segurança. |
| Ali não usa código de evento | Cadastrar/ativar regra em `promotions.json`. |
| TOP diário duplicado | Ver `digest_state.json`; versão atual persiste estado. |
| Steam sem candidatos | Ver `Reviews OK`, `Waitlist OK`, `Scored`, `Selecionados`. |
| Links ML sem comissão | Rodar `python login_ml.py` e conferir sessão. |

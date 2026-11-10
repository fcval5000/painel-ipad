# Painel de Notícias

Painel de notícias e clima para deixar ligado em iPad, tablet, celular ou TV. Usa o visual **druris-neon** dos dashboards do Home Assistant.

**Endereço:** https://fcval5000.github.io/painel-ipad/

## Como funciona

```
GitHub Actions (a cada ~15 min)          navegador (iPad / TV / celular)
scripts/fetch_news.py  ──►  branch "data"  ──►  index.html
  lê os feeds de feeds.json      news.json        + clima direto do Open-Meteo
```

- A coleta roda no servidor. Isso evita o bloqueio de CORS dos portais, o limite de taxa do rss2json e os problemas de acentuação do UOL.
- `news.json` fica num branch separado (`data`), substituído a cada execução, para não encher o histórico do `main`.
- Se o `news.json` não carregar ou estiver velho (mais de 90 min), a página tenta buscar pelo rss2json direto. Sem internet, mostra a última versão guardada no aparelho.

## Parâmetros pela URL

| Parâmetro | Exemplo | O que faz |
|---|---|---|
| `intervalo` | `?intervalo=20` | segundos por notícia (padrão 14) |
| `fontes` | `?fontes=g1-campinas,ge` | só essas fontes (ids de `feeds.json`) |
| `nome` | `?nome=Felipe` | saudação "Bom dia, Felipe." |
| `cidade`, `lat`, `lon` | `?cidade=Valinhos&lat=-22.97&lon=-46.99` | clima de outra cidade |
| `noturno` | `?noturno=0` ou `?noturno=22-7` | escurece a tela de madrugada (padrão 23h–6h). Um toque acende por 10 min |

Exemplo para a TV: `https://fcval5000.github.io/painel-ipad/?nome=Felipe&intervalo=18`

## Controles

- **Toque/clique** na notícia: abre a matéria.
- **Deslizar** para os lados, ou os botões ‹ ❚❚ ›: navegar e pausar.
- **Teclado / controle da TV:** ← → navegam, espaço pausa, Enter abre.
- **Fontes** no topo: toque para ligar/desligar. A escolha fica salva no aparelho.

## Adicionar ou trocar fontes

Edite `feeds.json` (id, nome, categoria, cor e URL do RSS). O workflow roda sozinho ao receber o push.

## iPad como painel fixo

1. Safari → Compartilhar → **Adicionar à Tela de Início** (abre em tela cheia).
2. Ajustes → Acessibilidade → **Acesso Guiado**, para travar no app.
3. A página pede para manter a tela ligada (Wake Lock), mas vale conferir Ajustes → Tela e Brilho → Bloqueio Automático → Nunca.

## Rodar localmente

```bash
python3 scripts/fetch_news.py      # gera news.json
python3 -m http.server 8000        # abra http://localhost:8000/?dados=news.json
```

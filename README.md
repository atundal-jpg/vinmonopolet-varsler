# vinmonopolet-varsler

Push-varsler (ntfy) når ting du venter på blir tilgjengelig.

- **Vinvarsler** – viner på ønskelisten som dukker opp i nærbutikkene dine eller
  kan bestilles: `check_products.py` + workflowen *Vinmonopolet Varsler*.
- **Billettvarsler** – billetter som legges ut for videresalg på
  `resale.fotball.no`: `check_tickets.py` + workflowen *Billettvarsler
  (fotball)*. Se [docs/billettvarsel.md](docs/billettvarsel.md).
- **Prisvarsler** – Samsung-TV-er som når «god pris» eller «knallpris» eller
  faller merkbart, f.eks. til Black Friday: `check_prices.py` + workflowen
  *Prisvarsler (TV)*. Ønskelista ligger i `data/tv_watchlist.json`, og alle
  priser logges i `data/tv_price_log.csv`. Se
  [docs/prisvarsel.md](docs/prisvarsel.md).

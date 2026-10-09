# Realism targets

The generator is synthetic (rule §4.7), but it is calibrated so that a simulated season looks
like a real one. Targets are **published league-wide averages** from the 2024/25 Premier
League season (380 matches). We use only aggregate figures, which are facts, not anyone's
dataset; no event-level data from any provider is used.

**Why not StatsBomb open data?** Its user agreement (§1.2.2) forbids commercially exploiting
"any analysis derived" from the data and (§1.4) requires the StatsBomb logo on any publication
built on it. Both conflict with a prize entry that must be solely our work (hackathon rule
4.11) and free of third-party trademarks.

`tests/test_realism.py` simulates a 380-match season and checks every row below.

| Metric | Real 2024/25 | Tolerance | Source |
|---|---|---|---|
| Goals per match | 2.93 (1,115 / 380) | ± 0.25 | [Wikipedia: 2024–25 Premier League](https://en.wikipedia.org/wiki/2024%E2%80%9325_Premier_League) |
| Passes per team per match | 447 (club range 341–605) | ± 10 % | [FootballCritic passes per game](https://www.footballcritic.com/premier-league/season-2024-2025/passes-per-game/2/72764) (mean of 20 clubs) |
| Pass completion | 83.4 % (club range 75–90 %) | ± 2.5 pp | [FotMob pass accuracy](https://www.fotmob.com/leagues/47/stats/season/23685/teams/accurate_pass_team/premier-league-teams) (mean of 19 clubs listed) |
| Shots per team per match | 13.1 | ± 1.5 | [The Analyst shot data](https://theanalyst.com/articles/premier-league-2024-25-shot-data): 8.3 outside-box shots/game = 31.7 % of shots |
| Share of shots from outside the box | 31.7 % | ± 6 pp | The Analyst, as above |
| Conversion, all shots | 11.2 % (2.93 / 26.2) | ± 1.5 pp | derived from the two rows above |
| Conversion inside / outside the box | 14.7 % / 4.2 % | ± 3 pp / ± 2 pp | The Analyst, as above |
| Fouls per team per match | 11.1 (club range 7.6–13.8) | ± 1.2 | [FotMob fouls per match](https://www.fotmob.com/leagues/47/stats/season/23685/teams/fk_foul_lost_team/premier-league-teams) (mean of 20 clubs) |
| Yellow cards per team per match | 2.04 (1,549 / 380 / 2) | ± 0.3 | [MyFootballFacts cards 2024–25](https://www.myfootballfacts.com/premier-league/all-time-premier-league/cards/premier-league-red-and-yellow-cards-2024-25/) |
| Red cards per match | 0.137 (52 / 380) | ± 0.07 | MyFootballFacts, as above |
| Home win / draw / away win | 40.8 % / 24.5 % / 34.7 % | ± 6 pp each | Wikipedia, as above |

Club spread matters as much as the mean: the best passing side in our league should look
like a possession giant and the weakest like a direct, low-possession side.

| Spread check | Target |
|---|---|
| Highest club average passes | ≥ 540 |
| Lowest club average passes | ≤ 380 |
| Highest / lowest club pass completion | ≥ 87 % / ≤ 79 % |

Not calibrated (no reliable public aggregate found): shots-on-target share, substitutions,
and possession-change rate. These keep the plausibility ranges in TEST_PLAN §2.

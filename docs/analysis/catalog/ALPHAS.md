# Alpha Zoo Catalog

Total modules with meta: **462**.

## academic (12)

| id | theme | columns | warmup | formula |
|----|-------|---------|-------:|---------|
| `academic_bab` | volatility | close | 253 | \mathrm{zscore}_{x}\bigl(-\,\mathrm{ts\_cov}(r_i, r_m, 252)  |
| `academic_carhart_mom` | momentum | close | 252 | \mathrm{zscore}_{x}\bigl((\mathrm{close}_t - \mathrm{close}_ |
| `academic_cma` | quality | volume | 120 | \mathrm{zscore}_{x}\bigl(-\Delta_{60}\log(\mathrm{ts\_mean}( |
| `academic_corr_rewire` | volatility | close | 142 | \mathrm{zscore}_{x}\Bigl(-\,\frac{1}{/J_i/}\sum_{j \in J_i}\ |
| `academic_high52w` | momentum | close | 252 | \mathrm{zscore}_{x}\bigl(\mathrm{close}_t / \mathrm{ts\_max} |
| `academic_hml` | value | close | 252 | \mathrm{zscore}_{x}\bigl(-(\mathrm{close}_t - \mathrm{close} |
| `academic_illiq` | liquidity | close,volume | 22 | \mathrm{zscore}_{x}\bigl(\mathrm{ts\_mean}(/r_t/ / (\mathrm{ |
| `academic_mkt_rf` | momentum | close | 21 | \mathrm{zscore}_{x}\bigl((\mathrm{close}_t - \mathrm{close}_ |
| `academic_retskew` | volatility | close | 61 | \mathrm{zscore}_{x}\bigl(-\mathrm{skew}_{60}(r_t)\bigr) |
| `academic_rmw` | quality | close | 60 | \mathrm{zscore}_{x}\bigl(-\mathrm{ts\_std}((\mathrm{close}_t |
| `academic_smb` | quality | close,volume | 60 | \mathrm{zscore}_{x}\bigl(-\log(\mathrm{ts\_mean}(\mathrm{vol |
| `academic_strev` | reversal | close | 21 | \mathrm{zscore}_{x}\bigl(-(\mathrm{close}_t - \mathrm{close} |

## alpha101 (101)

| id | theme | columns | warmup | formula |
|----|-------|---------|-------:|---------|
| `alpha101_001` | reversal,volatility | close | 25 | rank(ts_argmax(SignedPower((returns<0)?stddev(returns,20):cl |
| `alpha101_002` | volume,reversal | open,close,volume | 10 | -1 * correlation(rank(delta(log(volume), 2)), rank(((close-o |
| `alpha101_003` | volume,reversal | open,volume,close | 10 | -1 * correlation(rank(open), rank(volume), 10) |
| `alpha101_004` | reversal | low,close | 9 | -1 * Ts_Rank(rank(low), 9) |
| `alpha101_005` | reversal | open,close,vwap | 10 | rank((open - sum(vwap,10)/10)) * (-1 * abs(rank((close - vwa |
| `alpha101_006` | volume,reversal | open,volume,close | 10 | -1 * correlation(open, volume, 10) |
| `alpha101_007` | momentum,volume | close,volume | 67 | (adv20<volume)?((-1*ts_rank(abs(delta(close,7)),60))*sign(de |
| `alpha101_008` | reversal | open,close | 15 | -1 * rank((sum(open,5)*sum(returns,5)) - delay(sum(open,5)*s |
| `alpha101_009` | momentum | close | 6 | (0<ts_min(delta(close,1),5))?delta(close,1):((ts_max(delta(c |
| `alpha101_010` | momentum | close | 5 | rank((0<ts_min(delta(close,1),4))?delta(close,1):((ts_max(de |
| `alpha101_011` | volume,reversal | close,volume,vwap | 5 | (rank(ts_max(vwap-close,3))+rank(ts_min(vwap-close,3)))*rank |
| `alpha101_012` | volume,reversal | close,volume | 2 | sign(delta(volume,1)) * (-1 * delta(close,1)) |
| `alpha101_013` | volume | close,volume | 5 | -1 * rank(covariance(rank(close), rank(volume), 5)) |
| `alpha101_014` | volume,momentum | open,close,volume | 10 | (-1*rank(delta(returns,3))) * correlation(open, volume, 10) |
| `alpha101_015` | volume | high,volume,close | 6 | -1 * sum(rank(correlation(rank(high), rank(volume), 3)), 3) |
| `alpha101_016` | volume | high,volume,close | 5 | -1 * rank(covariance(rank(high), rank(volume), 5)) |
| `alpha101_017` | volume,reversal | close,volume | 25 | ((-1*rank(ts_rank(close,10)))*rank(delta(delta(close,1),1))) |
| `alpha101_018` | volatility | open,close | 10 | -1 * rank(stddev(abs(close-open),5) + (close-open) + correla |
| `alpha101_019` | momentum | close | 250 | (-1*sign((close-delay(close,7))+delta(close,7))) * (1+rank(1 |
| `alpha101_020` | reversal | open,high,low,close | 2 | (((-1*rank(open-delay(high,1)))*rank(open-delay(close,1)))*r |
| `alpha101_021` | momentum,volatility | close,volume | 20 | complex piecewise; see paper |
| `alpha101_022` | volume,volatility | high,close,volume | 25 | -1 * (delta(correlation(high,volume,5),5) * rank(stddev(clos |
| `alpha101_023` | momentum | high,close | 20 | ((sum(high,20)/20) < high) ? (-1*delta(high,2)) : 0 |
| `alpha101_024` | momentum | close | 200 | complex piecewise; see paper |
| `alpha101_025` | momentum,volume | high,close,volume,vwap | 21 | rank((((-1*returns)*adv20)*vwap)*(high-close)) |
| `alpha101_026` | volume | high,volume,close | 13 | -1 * ts_max(correlation(ts_rank(volume,5),ts_rank(high,5),5) |
| `alpha101_027` | volume | volume,vwap,close | 10 | (0.5<rank((sum(correlation(rank(volume),rank(vwap),6),2)/2.0 |
| `alpha101_028` | volume | high,low,close,volume | 25 | scale((correlation(adv20,low,5) + (high+low)/2) - close) |
| `alpha101_029` | reversal,volume | close,volume | 12 | min(product(rank(rank(scale(log(sum(ts_min(rank(rank(-1*rank |
| `alpha101_030` | momentum,volume | close,volume | 20 | ((1-rank(sign(d1)+sign(d2)+sign(d3))) * sum(volume,5)) / sum |
| `alpha101_031` | momentum | low,close,volume | 25 | rank(rank(rank(decay_linear(-1*rank(rank(delta(close,10))),1 |
| `alpha101_032` | momentum | close,vwap | 235 | scale(sum(close,7)/7 - close) + 20*scale(correlation(vwap, d |
| `alpha101_033` | reversal | open,close | 1 | rank(-1*(1-open/close)) |
| `alpha101_034` | volatility | close | 6 | rank((1-rank(stddev(returns,2)/stddev(returns,5))) + (1-rank |
| `alpha101_035` | volume,momentum | high,low,close,volume | 33 | ts_rank(volume,32) * (1 - ts_rank((close+high-low),16)) * (1 |
| `alpha101_036` | momentum,volume | open,close,volume,vwap | 200 | weighted sum; see paper |
| `alpha101_037` | momentum | open,close | 201 | rank(correlation(delay(open-close,1),close,200)) + rank(open |
| `alpha101_038` | reversal | open,close | 10 | (-1*rank(ts_rank(close,10))) * rank(close/open) |
| `alpha101_039` | momentum,volume | close,volume | 250 | (-1*rank(delta(close,7)*(1-rank(decay_linear(volume/adv20,9) |
| `alpha101_040` | volatility,volume | high,volume,close | 10 | (-1*rank(stddev(high,10))) * correlation(high,volume,10) |
| `alpha101_041` | reversal | high,low,vwap,close | 1 | (high*low)^0.5 - vwap |
| `alpha101_042` | reversal | close,vwap | 1 | rank(vwap-close) / rank(vwap+close) |
| `alpha101_043` | volume,momentum | close,volume | 39 | ts_rank(volume/adv20,20) * ts_rank(-1*delta(close,7),8) |
| `alpha101_044` | volume | high,volume,close | 5 | -1 * correlation(high, rank(volume), 5) |
| `alpha101_045` | momentum,volume | close,volume | 25 | -1 * (rank(sum(delay(close,5),20)/20)*correlation(close,volu |
| `alpha101_046` | momentum | close | 21 | complex piecewise; see paper |
| `alpha101_047` | volume,momentum | high,close,volume,vwap | 25 | ((rank(1/close)*volume/adv20) * (high*rank(high-close)/(sum( |
| `alpha101_048` | momentum,volatility | close | 251 | indneutralize(...subindustry...) / sum((delta(close,1)/delay |
| `alpha101_049` | momentum | close | 21 | (((delay(close,20)-delay(close,10))/10 - (delay(close,10)-cl |
| `alpha101_050` | volume | volume,vwap,close | 10 | -1 * ts_max(rank(correlation(rank(volume), rank(vwap), 5)),  |
| `alpha101_051` | momentum | close | 21 | (...< -0.05) ? 1 : -1*(close-delay(close,1)) |
| `alpha101_052` | momentum | low,close,volume | 240 | ((-1*ts_min(low,5)+delay(ts_min(low,5),5)) * rank((sum(retur |
| `alpha101_053` | reversal | high,low,close | 10 | -1 * delta(((close-low) - (high-close))/(close-low), 9) |
| `alpha101_054` | reversal | open,high,low,close | 1 | -1 * ((low-close)*(open^5)) / ((low-high)*(close^5)) |
| `alpha101_055` | volume,reversal | high,low,close,volume | 17 | -1 * correlation(rank((close-ts_min(low,12))/(ts_max(high,12 |
| `alpha101_056` | momentum | close | 10 | 0 - 1*(rank(sum(returns,10)/sum(sum(returns,2),3)) * rank((r |
| `alpha101_057` | reversal | close,vwap | 32 | 0 - 1 * ((close-vwap) / decay_linear(rank(ts_argmax(close,30 |
| `alpha101_058` | volume | volume,vwap,close | 25 | -1 * Ts_Rank(decay_linear(correlation(IndNeutralize(vwap, se |
| `alpha101_059` | volume | volume,vwap,close | 30 | -1 * Ts_Rank(decay_linear(correlation(IndNeutralize(vwap*0.7 |
| `alpha101_060` | volume | high,low,close,volume | 10 | 0 - (2*scale(rank((((close-low)-(high-close))/(high-low))*vo |
| `alpha101_061` | volume | volume,vwap,close | 197 | rank(vwap - ts_min(vwap,16)) < rank(correlation(vwap, adv180 |
| `alpha101_062` | volume | open,high,low,volume,vwap,close | 35 | (rank(correlation(vwap, sum(adv20,22), 10)) < rank(((rank(op |
| `alpha101_063` | volume,momentum | open,close,volume,vwap | 204 | (rank(decay_linear(delta(IndNeutralize(close, industry), 2), |
| `alpha101_064` | volume | open,high,low,volume,vwap,close | 136 | (rank(correlation(sum(0.178*open+0.822*low,13), sum(adv120,1 |
| `alpha101_065` | volume | open,volume,vwap,close | 65 | (rank(correlation(0.008*open+0.992*vwap, sum(adv60,9), 6)) < |
| `alpha101_066` | momentum | open,high,low,vwap,close | 18 | (rank(decay_linear(delta(vwap,4), 7)) + Ts_Rank(decay_linear |
| `alpha101_067` | volume | high,volume,vwap,close | 25 | (rank(high-ts_min(high,2))^rank(correlation(IndNeutralize(vw |
| `alpha101_068` | volume | high,low,close,volume | 36 | (Ts_Rank(correlation(rank(high), rank(adv15), 9), 14) < rank |
| `alpha101_069` | volume | close,volume,vwap | 32 | (rank(ts_max(delta(IndNeutralize(vwap, industry), 3), 5))^Ts |
| `alpha101_070` | momentum,volume | close,volume,vwap | 84 | (rank(delta(vwap,1))^Ts_Rank(correlation(IndNeutralize(close |
| `alpha101_071` | volume,reversal | open,low,close,volume,vwap | 226 | max(Ts_Rank(decay_linear(correlation(Ts_Rank(close,3), Ts_Ra |
| `alpha101_072` | volume | high,low,volume,vwap,close | 57 | rank(decay_linear(correlation((high+low)/2, adv40, 9), 10))  |
| `alpha101_073` | volume | open,low,vwap,close | 21 | max(rank(decay_linear(delta(vwap,5), 3)), Ts_Rank(decay_line |
| `alpha101_074` | volume | high,close,volume,vwap | 60 | (rank(correlation(close, sum(adv30,37), 15)) < rank(correlat |
| `alpha101_075` | volume | low,volume,vwap,close | 61 | rank(correlation(vwap, volume, 4)) < rank(correlation(rank(l |
| `alpha101_076` | volume | low,volume,vwap,close | 141 | max(rank(decay_linear(delta(vwap,1),12)), Ts_Rank(decay_line |
| `alpha101_077` | volume | high,low,volume,vwap,close | 47 | min(rank(decay_linear((high+low)/2 + high - (vwap+high), 20) |
| `alpha101_078` | volume | low,volume,vwap,close | 46 | rank(correlation(sum(0.352*low+0.648*vwap, 20), sum(adv40,20 |
| `alpha101_079` | volume,momentum | open,close,volume,vwap | 172 | rank(delta(IndNeutralize(0.607*close+0.393*open, sector), 1) |
| `alpha101_080` | momentum,volume | open,high,volume,close | 19 | (rank(Sign(delta(IndNeutralize(0.868*open+0.132*high, subind |
| `alpha101_081` | volume | volume,vwap,close | 70 | (rank(Log(product(rank((rank(correlation(vwap, sum(adv10,50) |
| `alpha101_082` | volume | open,volume,close | 35 | min(rank(decay_linear(delta(open,1),15)), Ts_Rank(decay_line |
| `alpha101_083` | volume,volatility | high,low,close,volume,vwap | 7 | (rank(delay((high-low)/(sum(close,5)/5), 2)) * rank(rank(vol |
| `alpha101_084` | momentum | close,vwap | 35 | SignedPower(Ts_Rank(vwap-ts_max(vwap,15), 21), delta(close,5 |
| `alpha101_085` | volume | high,low,close,volume | 39 | rank(correlation(0.877*high+0.123*close, adv30, 10))^rank(co |
| `alpha101_086` | volume | open,close,volume,vwap | 44 | (Ts_Rank(correlation(close, sum(adv20,15), 6), 20) < rank((o |
| `alpha101_087` | momentum | close,vwap,volume | 110 | max(rank(decay_linear(delta(0.37*close+0.63*vwap, 2), 3)), T |
| `alpha101_088` | volume | open,high,low,close,volume | 94 | min(rank(decay_linear((rank(open)+rank(low))-(rank(high)+ran |
| `alpha101_089` | volume,momentum | low,volume,vwap,close | 30 | Ts_Rank(decay_linear(correlation(low, adv10, 7), 6), 4) - Ts |
| `alpha101_090` | volume | low,close,volume | 46 | (rank(close-ts_max(close,5))^Ts_Rank(correlation(IndNeutrali |
| `alpha101_091` | volume | close,volume,vwap | 35 | (Ts_Rank(decay_linear(decay_linear(correlation(IndNeutralize |
| `alpha101_092` | volume | open,high,low,close,volume | 49 | min(Ts_Rank(decay_linear(((high+low)/2 + close < low+open),  |
| `alpha101_093` | volume | close,volume,vwap | 123 | Ts_Rank(decay_linear(correlation(IndNeutralize(vwap, industr |
| `alpha101_094` | volume | volume,vwap,close | 82 | (rank(vwap-ts_min(vwap,12))^Ts_Rank(correlation(Ts_Rank(vwap |
| `alpha101_095` | volume | open,high,low,volume,close | 63 | rank(open-ts_min(open,13)) < Ts_Rank((rank(correlation(sum(( |
| `alpha101_096` | volume | close,volume,vwap | 103 | max(Ts_Rank(decay_linear(correlation(rank(vwap), rank(volume |
| `alpha101_097` | volume | low,volume,vwap,close | 128 | (rank(decay_linear(delta(IndNeutralize(0.721*low+0.279*vwap, |
| `alpha101_098` | volume | open,volume,vwap,close | 56 | rank(decay_linear(correlation(vwap, sum(adv5,26), 5), 7)) -  |
| `alpha101_099` | volume | high,low,volume,close | 68 | (rank(correlation(sum((high+low)/2, 20), sum(adv60, 20), 9)) |
| `alpha101_100` | volume,momentum | high,low,close,volume | 30 | 0 - 1*((1.5*scale(IN(IN(rank(((close-low)-(high-close))/(hig |
| `alpha101_101` | reversal | open,high,low,close | 1 | (close - open) / ((high - low) + 0.001) |

## fundamental (4)

| id | theme | columns | warmup | formula |
|----|-------|---------|-------:|---------|
| `fund_asset_growth` | growth | fund:asset_growth | 1 | -\mathrm{zscore}_{x}(\Delta \mathrm{total\_assets}_{YoY}) |
| `fund_earnings_yield` | value | close,fund:net_income,fund:shares_dilute | 1 | \mathrm{zscore}_{x}\left(\frac{\mathrm{net\_income}}{\mathrm |
| `fund_gross_profitability` | quality | fund:gross_profitability | 1 | \mathrm{zscore}_{x}(\mathrm{gross\_profit}/\mathrm{total\_as |
| `fund_roe` | quality | fund:roe | 1 | \mathrm{zscore}_{x}(\mathrm{ROE}) |

## gtja191 (191)

| id | theme | columns | warmup | formula |
|----|-------|---------|-------:|---------|
| `gtja191_001` | volume,reversal | volume,close,open | 7 | (-1 * CORR(RANK(DELTA(LOG(VOLUME), 1)), RANK(((CLOSE - OPEN) |
| `gtja191_002` | reversal,microstructure | close,high,low | 2 | (-1 * DELTA(((CLOSE - LOW) - (HIGH - CLOSE)) / (HIGH - LOW), |
| `gtja191_003` | momentum | close,high,low | 7 | SUM((CLOSE=DELAY(CLOSE,1)?0:CLOSE-(CLOSE>DELAY(CLOSE,1)?MIN( |
| `gtja191_004` | momentum,volume | close,volume | 20 | ((((SUM(CLOSE,8)/8)+STD(CLOSE,8))<(SUM(CLOSE,2)/2))?(-1):((S |
| `gtja191_005` | volume | volume,high | 13 | (-1 * TSMAX(CORR(TSRANK(VOLUME,5), TSRANK(HIGH,5), 5), 3)) |
| `gtja191_006` | reversal | open,high | 5 | (RANK(SIGN(DELTA((OPEN*0.85+HIGH*0.15), 4))) * -1) |
| `gtja191_007` | volume,microstructure | close,volume,amount | 4 | ((RANK(MAX((VWAP-CLOSE),3)) + RANK(MIN((VWAP-CLOSE),3))) * R |
| `gtja191_008` | reversal | high,low,volume,amount | 5 | RANK(DELTA(((HIGH+LOW)/2)*0.2 + VWAP*0.8, 4)) * -1 |
| `gtja191_009` | volume,microstructure | high,low,volume | 8 | SMA(((HIGH+LOW)/2-(DELAY(HIGH,1)+DELAY(LOW,1))/2)*(HIGH-LOW) |
| `gtja191_010` | volatility,reversal | close | 21 | RANK(MAX(((RET<0)?STD(RET,20):CLOSE)^2,5)) |
| `gtja191_011` | volume,microstructure | close,high,low,volume | 7 | SUM(((CLOSE-LOW)-(HIGH-CLOSE))/(HIGH-LOW)*VOLUME,6) |
| `gtja191_012` | reversal,microstructure | open,close,volume,amount | 11 | (RANK((OPEN - (SUM(VWAP,10)/10))) * (-1 * RANK(ABS((CLOSE -  |
| `gtja191_013` | microstructure | high,low,volume,amount | 1 | (((HIGH*LOW)^0.5) - VWAP) |
| `gtja191_014` | momentum | close | 6 | CLOSE - DELAY(CLOSE,5) |
| `gtja191_015` | reversal | open,close | 2 | (OPEN/DELAY(CLOSE,1) - 1) |
| `gtja191_016` | volume,microstructure | volume,amount | 11 | (-1 * TSMAX(RANK(CORR(RANK(VOLUME), RANK(VWAP), 5)), 5)) |
| `gtja191_017` | reversal | close,volume,amount | 16 | (RANK(VWAP - MAX(VWAP,15))^DELTA(CLOSE,5)) |
| `gtja191_018` | momentum | close | 6 | CLOSE/DELAY(CLOSE,5) |
| `gtja191_019` | reversal | close | 6 | (CLOSE<DELAY(CLOSE,5)?(CLOSE-DELAY(CLOSE,5))/DELAY(CLOSE,5): |
| `gtja191_020` | momentum | close | 7 | ((CLOSE-DELAY(CLOSE,6))/DELAY(CLOSE,6))*100 |
| `gtja191_021` | momentum | close | 12 | REGBETA(MEAN(CLOSE,6), SEQUENCE(6)) |
| `gtja191_022` | reversal | close | 10 | SMA(((CLOSE-MEAN(CLOSE,6))/MEAN(CLOSE,6) - DELAY((CLOSE-MEAN |
| `gtja191_023` | volatility | close | 22 | SMA((CLOSE>DELAY(CLOSE,1)?STD(CLOSE,20):0),20,1)/(SMA((CLOSE |
| `gtja191_024` | momentum | close | 6 | SMA(CLOSE-DELAY(CLOSE,5),5,1) |
| `gtja191_025` | momentum,volume | close,volume | 61 | ((-1*RANK((DELTA(CLOSE,7)*(1-RANK(DECAYLINEAR((VOLUME/MEAN(V |
| `gtja191_026` | momentum,microstructure | close,volume,amount | 35 | ((((SUM(CLOSE,7)/7)-CLOSE))+((CORR(VWAP,DELAY(CLOSE,5),230)) |
| `gtja191_027` | momentum | close | 18 | WMA((CLOSE-DELAY(CLOSE,3))/DELAY(CLOSE,3)*100 + (CLOSE-DELAY |
| `gtja191_028` | momentum | close,high,low | 12 | 3*SMA((CLOSE-TSMIN(LOW,9))/(TSMAX(HIGH,9)-TSMIN(LOW,9))*100, |
| `gtja191_029` | momentum,volume | close,volume | 7 | (CLOSE-DELAY(CLOSE,6))/DELAY(CLOSE,6)*VOLUME |
| `gtja191_030` | volatility | close | 21 | WMA((REGRESI(CLOSE/DELAY(CLOSE,1)-1, MKT_RET, SMB, HML, 60)) |
| `gtja191_031` | reversal | close | 13 | (CLOSE-MEAN(CLOSE,12))/MEAN(CLOSE,12)*100 |
| `gtja191_032` | volume | high,volume | 7 | (-1 * SUM(RANK(CORR(RANK(HIGH), RANK(VOLUME), 3)), 3)) |
| `gtja191_033` | momentum,volume | low,close,volume | 61 | ((((-1*TSMIN(LOW,5))+DELAY(TSMIN(LOW,5),5))*RANK(((SUM(RET,2 |
| `gtja191_034` | reversal | close | 13 | MEAN(CLOSE,12)/CLOSE |
| `gtja191_035` | volume | open,volume | 25 | (MIN(RANK(DECAYLINEAR(DELTA(OPEN,1),15)), RANK(DECAYLINEAR(C |
| `gtja191_036` | volume | volume,amount | 8 | RANK(SUM(CORR(RANK(VOLUME), RANK(VWAP), 6), 2)) |
| `gtja191_037` | momentum | open,close | 16 | (-1*RANK(((SUM(OPEN,5)*SUM(RET,5))-DELAY((SUM(OPEN,5)*SUM(RE |
| `gtja191_038` | reversal | high | 21 | (((SUM(HIGH,20)/20)<HIGH)?(-1*DELTA(HIGH,2)):0) |
| `gtja191_039` | volume | close,open,volume,amount | 63 | ((RANK(DECAYLINEAR(DELTA(CLOSE,2),8)) - RANK(DECAYLINEAR(COR |
| `gtja191_040` | volume | close,volume | 27 | SUM((CLOSE>DELAY(CLOSE,1)?VOLUME:0),26)/SUM((CLOSE<=DELAY(CL |
| `gtja191_041` | microstructure | volume,amount | 9 | (RANK(MAX(DELTA(VWAP,3),5))*-1) |
| `gtja191_042` | volume,volatility | high,volume | 11 | ((-1*RANK(STD(HIGH,10)))*CORR(HIGH,VOLUME,10)) |
| `gtja191_043` | volume,momentum | close,volume | 7 | SUM((CLOSE>DELAY(CLOSE,1)?VOLUME:(CLOSE<DELAY(CLOSE,1)?-VOLU |
| `gtja191_044` | volume | low,volume,amount | 27 | (TSRANK(DECAYLINEAR(CORR(LOW,MEAN(VOLUME,10),7),6),4)+TSRANK |
| `gtja191_045` | volume | close,open,volume,amount | 44 | (RANK(DELTA((((CLOSE*0.6)+(OPEN*0.4))),1)) * RANK(CORR(VWAP, |
| `gtja191_046` | reversal | close | 25 | (MEAN(CLOSE,3)+MEAN(CLOSE,6)+MEAN(CLOSE,12)+MEAN(CLOSE,24))/ |
| `gtja191_047` | reversal | close,high,low | 10 | SMA((TSMAX(HIGH,6)-CLOSE)/(TSMAX(HIGH,6)-TSMIN(LOW,6))*100,9 |
| `gtja191_048` | volume,momentum | close,volume | 21 | -1*((RANK((SIGN((CLOSE-DELAY(CLOSE,1)))+SIGN((DELAY(CLOSE,1) |
| `gtja191_049` | reversal | high,low | 13 | SUM(((HIGH+LOW)>=(DELAY(HIGH,1)+DELAY(LOW,1))?0:MAX(ABS(HIGH |
| `gtja191_050` | reversal | high,low | 13 | SUM(up_move,12)/(SUM(up_move,12)+SUM(dn_move,12)) - SUM(dn_m |
| `gtja191_051` | reversal | high,low | 13 | SUM(up_move,12)/(SUM(up_move,12)+SUM(dn_move,12)) |
| `gtja191_052` | microstructure | high,low,close | 27 | SUM(MAX(0,HIGH-DELAY((HIGH+LOW+CLOSE)/3,1)),26) / SUM(MAX(0, |
| `gtja191_053` | momentum | close | 13 | COUNT(CLOSE>DELAY(CLOSE,1),12)/12*100 |
| `gtja191_054` | volatility,microstructure | close,open | 11 | ((-1*RANK((STD(ABS(CLOSE-OPEN),10)+(CLOSE-OPEN))+CORR(CLOSE, |
| `gtja191_055` | microstructure | close,high,low,open | 22 | SUM(16*(CLOSE-DELAY(CLOSE,1)+(CLOSE-OPEN)/2+DELAY(CLOSE,1)-D |
| `gtja191_056` | volume | open,high,low,volume | 60 | (RANK(OPEN-TSMIN(OPEN,12)) < RANK((RANK(CORR(SUM(((HIGH+LOW) |
| `gtja191_057` | momentum | close,high,low | 10 | SMA((CLOSE-TSMIN(LOW,9))/(TSMAX(HIGH,9)-TSMIN(LOW,9))*100,3, |
| `gtja191_058` | momentum | close | 21 | COUNT(CLOSE>DELAY(CLOSE,1),20)/20*100 |
| `gtja191_059` | momentum | close,high,low | 22 | SUM((CLOSE=DELAY(CLOSE,1)?0:CLOSE-(CLOSE>DELAY(CLOSE,1)?MIN( |
| `gtja191_060` | volume,microstructure | close,high,low,volume | 21 | SUM(((CLOSE-LOW)-(HIGH-CLOSE))/(HIGH-LOW)*VOLUME, 20) |
| `gtja191_061` | volume | volume,amount,low | 53 | (MAX(RANK(DECAYLINEAR(DELTA(VWAP,1),12)), RANK(DECAYLINEAR(R |
| `gtja191_062` | volume | high,volume | 6 | ((-1*CORR(HIGH,RANK(VOLUME),5))) |
| `gtja191_063` | momentum | close | 7 | SMA(MAX(CLOSE-DELAY(CLOSE,1),0),6,1)/SMA(ABS(CLOSE-DELAY(CLO |
| `gtja191_064` | volume | close,volume,amount | 30 | (MAX(RANK(DECAYLINEAR(CORR(RANK(VWAP),RANK(VOLUME),4),4)),RA |
| `gtja191_065` | reversal | close | 7 | MEAN(CLOSE,6)/CLOSE |
| `gtja191_066` | reversal | close | 7 | (CLOSE-MEAN(CLOSE,6))/MEAN(CLOSE,6)*100 |
| `gtja191_067` | momentum | close | 25 | SMA(MAX(CLOSE-DELAY(CLOSE,1),0),24,1)/SMA(ABS(CLOSE-DELAY(CL |
| `gtja191_068` | volume | high,low,volume | 16 | SMA(((HIGH+LOW)/2-(DELAY(HIGH,1)+DELAY(LOW,1))/2)*(HIGH-LOW) |
| `gtja191_069` | microstructure | open,high,low | 22 | (SUM(DTM,20)>SUM(DBM,20)?(SUM(DTM,20)-SUM(DBM,20))/SUM(DTM,2 |
| `gtja191_070` | volatility,volume | amount | 7 | STD(AMOUNT,6) |
| `gtja191_071` | reversal | close | 25 | (CLOSE-MEAN(CLOSE,24))/MEAN(CLOSE,24)*100 |
| `gtja191_072` | reversal | close,high,low | 16 | SMA((TSMAX(HIGH,6)-CLOSE)/(TSMAX(HIGH,6)-TSMIN(LOW,6))*100,1 |
| `gtja191_073` | volume | close,volume,amount | 35 | ((TSRANK(DECAYLINEAR(DECAYLINEAR(CORR((CLOSE),VOLUME,10),16) |
| `gtja191_074` | volume | low,volume,amount | 30 | (RANK(CORR(SUM(((LOW*0.35)+(VWAP*0.65)),20),SUM(MEAN(VOLUME, |
| `gtja191_075` | sentiment,momentum | close,open | 30 | COUNT((CLOSE>OPEN & BENCHMARKINDEXCLOSE<DELAY(BENCHMARKINDEX |
| `gtja191_076` | volatility,volume | close,volume | 22 | STD(ABS((CLOSE/DELAY(CLOSE,1)-1))/VOLUME,20)/MEAN(ABS((CLOSE |
| `gtja191_077` | volume | high,low,volume,amount | 37 | MIN(RANK(DECAYLINEAR(((HIGH+LOW)/2+HIGH-(VWAP+HIGH)),20)),RA |
| `gtja191_078` | reversal | high,low,close | 23 | ((HIGH+LOW+CLOSE)/3-MA((HIGH+LOW+CLOSE)/3,12))/(0.015*MEAN(A |
| `gtja191_079` | momentum | close | 13 | SMA(MAX(CLOSE-DELAY(CLOSE,1),0),12,1)/SMA(ABS(CLOSE-DELAY(CL |
| `gtja191_080` | volume | volume | 6 | (VOLUME-DELAY(VOLUME,5))/DELAY(VOLUME,5)*100 |
| `gtja191_081` | volume | volume | 22 | SMA(VOLUME,21,2) |
| `gtja191_082` | reversal | close,high,low | 21 | SMA((TSMAX(HIGH,6)-CLOSE)/(TSMAX(HIGH,6)-TSMIN(LOW,6))*100,2 |
| `gtja191_083` | volume | high,volume | 6 | (-1*RANK(COVIANCE(RANK(HIGH),RANK(VOLUME),5))) |
| `gtja191_084` | volume,momentum | close,volume | 21 | SUM(CLOSE>DELAY(CLOSE,1)?VOLUME:(CLOSE<DELAY(CLOSE,1)?-VOLUM |
| `gtja191_085` | volume,momentum | close,volume | 39 | (TSRANK((VOLUME/MEAN(VOLUME,20)),20)*TSRANK((-1*DELTA(CLOSE, |
| `gtja191_086` | momentum | close | 22 | ((0.25 < (((DELAY(CLOSE,20)-DELAY(CLOSE,10))/10) - ((DELAY(C |
| `gtja191_087` | microstructure | close,open,high,low,volume,amount | 22 | ((RANK(DECAYLINEAR(DELTA(VWAP,4),7))+TSRANK(DECAYLINEAR((((L |
| `gtja191_088` | momentum | close | 21 | (CLOSE-DELAY(CLOSE,20))/DELAY(CLOSE,20)*100 |
| `gtja191_089` | momentum | close | 28 | 2*(SMA(CLOSE,13,2)-SMA(CLOSE,27,2)-SMA(SMA(CLOSE,13,2)-SMA(C |
| `gtja191_090` | volume | volume,amount | 6 | ((-1*RANK(CORR(RANK(VWAP),RANK(VOLUME),5)))) |
| `gtja191_091` | volume,reversal | close,low,volume | 35 | ((-1*RANK((CLOSE-MAX(CLOSE,5))))*RANK(CORR(MEAN(VOLUME,40),L |
| `gtja191_092` | volume | close,volume,amount | 60 | (MAX(RANK(DECAYLINEAR(DELTA(((CLOSE*0.35)+(VWAP*0.65)),2),3) |
| `gtja191_093` | microstructure | open,low | 22 | SUM((OPEN>=DELAY(OPEN,1)?0:MAX(OPEN-LOW,OPEN-DELAY(OPEN,1))) |
| `gtja191_094` | volume,momentum | close,volume | 31 | SUM(CLOSE>DELAY(CLOSE,1)?VOLUME:(CLOSE<DELAY(CLOSE,1)?-VOLUM |
| `gtja191_095` | volatility,volume | amount | 21 | STD(AMOUNT,20) |
| `gtja191_096` | momentum | close,high,low | 12 | SMA(SMA((CLOSE-TSMIN(LOW,9))/(TSMAX(HIGH,9)-TSMIN(LOW,9))*10 |
| `gtja191_097` | volatility,volume | volume | 11 | STD(VOLUME,10) |
| `gtja191_098` | reversal | close | 60 | ((((DELTA((SUM(CLOSE,100)/100),100)/DELAY(CLOSE,100))<0.05)  |
| `gtja191_099` | volume | close,volume | 6 | (-1*RANK(COVIANCE(RANK(CLOSE),RANK(VOLUME),5))) |
| `gtja191_100` | volatility,volume | volume | 21 | STD(VOLUME,20) |
| `gtja191_101` | volume,momentum | open,high,low,close,volume,amount | 80 | ((rank(ts\_corr(close, sum(ts\_mean(volume,30),37), 15)) < r |
| `gtja191_102` | volume | close,volume | 7 | sma(max(volume-delay(volume,1),0),6,1)/sma(abs(volume-delay( |
| `gtja191_103` | reversal | close,low | 20 | ((20-lowday(low,20))/20)*100 |
| `gtja191_104` | volume,volatility | open,high,low,close,volume | 25 | -1*delta(corr(high,volume,5),5)*rank(std(close,20)) |
| `gtja191_105` | volume | open,volume,close | 10 | -1*corr(rank(open),rank(volume),10) |
| `gtja191_106` | momentum | close | 21 | close-delay(close,20) |
| `gtja191_107` | reversal | open,high,low,close | 2 | -1*rank(open-delay(high,1))*rank(open-delay(close,1))*rank(o |
| `gtja191_108` | reversal,volume | open,high,low,close,volume,amount | 125 | (rank(high-min(high,2))^rank(corr(vwap,mean(volume,120),6))) |
| `gtja191_109` | volatility | close,high,low | 20 | sma(high-low,10,2)/sma(sma(high-low,10,2),10,2) |
| `gtja191_110` | momentum | close,high,low | 21 | sum(max(0,high-delay(close,1)),20)/sum(max(0,delay(close,1)- |
| `gtja191_111` | volume,microstructure | open,high,low,close,volume | 12 | sma(v*((c-l)-(h-c))/(h-l),11,2)-sma(v*((c-l)-(h-c))/(h-l),4, |
| `gtja191_112` | momentum | close | 13 | (sum_up(12)-sum_down(12))/(sum_up(12)+sum_down(12))*100 |
| `gtja191_113` | volume | close,volume | 27 | -1*(rank(mean(delay(c,5),20))*corr(c,v,2))*rank(corr(sum(c,5 |
| `gtja191_114` | volume,volatility | open,high,low,close,volume,amount | 7 | see body |
| `gtja191_115` | volume | open,high,low,close,volume | 40 | rank(corr(0.9h+0.1c,mean(v,30),10))^rank(corr(tsrank((h+l)/2 |
| `gtja191_116` | momentum | close | 20 | regbeta(close,sequence(20),20) |
| `gtja191_117` | volume,momentum | close,high,low,volume | 33 | tsrank(v,32)*(1-tsrank(c+h-l,16))*(1-tsrank(ret,32)) |
| `gtja191_118` | reversal | open,high,low,close | 20 | sum(h-o,20)/sum(o-l,20)*100 |
| `gtja191_119` | volume | open,high,low,close,volume,amount | 60 | see body |
| `gtja191_120` | reversal | open,high,low,close,volume,amount | 1 | rank(vwap-close)/rank(vwap+close) |
| `gtja191_121` | volume | open,high,low,close,volume,amount | 80 | see body |
| `gtja191_122` | momentum | close | 40 | see body |
| `gtja191_123` | volume | open,high,low,close,volume | 90 | see body |
| `gtja191_124` | reversal | open,high,low,close,volume,amount | 32 | (close-vwap)/decay_linear(rank(tsmax(close,30)),2) |
| `gtja191_125` | volume | open,high,low,close,volume,amount | 120 | see body |
| `gtja191_126` | reversal | close,high,low | 1 | (c+h+l)/3 |
| `gtja191_127` | volatility | close | 24 | sqrt(mean((100*(c-tsmax(c,12))/tsmax(c,12))^2,12)) |
| `gtja191_128` | momentum | open,high,low,close,volume | 16 | see body |
| `gtja191_129` | momentum | close | 13 | sum(abs(c-delay(c,1)) if dc<0 else 0,12) |
| `gtja191_130` | volume | open,high,low,close,volume,amount | 60 | see body |
| `gtja191_131` | volume | open,high,low,close,volume,amount | 84 | rank(delta(vwap,1))^tsrank(corr(close,mean(v,50),18),18) |
| `gtja191_132` | liquidity | close,amount | 20 | mean(amount,20) |
| `gtja191_133` | momentum | close,high,low | 20 | ((20-highday(high,20))/20)*100-((20-lowday(low,20))/20)*100 |
| `gtja191_134` | momentum,volume | close,volume | 13 | (close-delay(close,12))/delay(close,12)*volume |
| `gtja191_135` | momentum | close | 22 | sma(delay(c/delay(c,20),1),20,1) |
| `gtja191_136` | momentum,volume | open,close,volume | 11 | -1*rank(delta(ret,3))*corr(open,volume,10) |
| `gtja191_137` | volatility | open,high,low,close | 2 | see body |
| `gtja191_138` | volume | open,high,low,close,volume,amount | 119 | see body |
| `gtja191_139` | volume | open,volume,close | 10 | -1*corr(open,volume,10) |
| `gtja191_140` | volume | open,high,low,close,volume | 100 | see body |
| `gtja191_141` | volume | high,volume,close | 24 | rank(corr(rank(high),rank(mean(v,15)),9))*-1 |
| `gtja191_142` | volume,reversal | close,volume | 26 | see body |
| `gtja191_143` | momentum | close | 2 | cumprod(1 + (c/delay(c,1)-1) if c>delay(c,1) else 0) |
| `gtja191_144` | liquidity | close,amount | 21 | see body |
| `gtja191_145` | volume | close,volume | 26 | (mean(v,9)-mean(v,26))/mean(v,12)*100 |
| `gtja191_146` | momentum | close | 81 | see body |
| `gtja191_147` | momentum | close | 24 | regbeta(mean(close,12),sequence(12)) |
| `gtja191_148` | volume | open,high,low,close,volume | 75 | see body |
| `gtja191_149` | momentum | close | 253 | see body |
| `gtja191_150` | volume | close,high,low,volume | 1 | (close+high+low)/3*volume |
| `gtja191_151` | momentum | close | 21 | sma(close-delay(close,20),20,1) |
| `gtja191_152` | momentum | close | 50 | see body |
| `gtja191_153` | momentum | close | 24 | (mean(c,3)+mean(c,6)+mean(c,12)+mean(c,24))/4 |
| `gtja191_154` | volume | open,high,low,close,volume,amount | 198 | see body |
| `gtja191_155` | volume | close,volume | 40 | sma(v,13,2)-sma(v,27,2)-sma(sma(v,13,2)-sma(v,27,2),10,2) |
| `gtja191_156` | volume | open,high,low,close,volume,amount | 10 | see body |
| `gtja191_157` | volume | close | 12 | see body |
| `gtja191_158` | volatility | close,high,low | 16 | ((h-sma(c,15,2))-(l-sma(c,15,2)))/c |
| `gtja191_159` | momentum | open,high,low,close,volume | 25 | see body |
| `gtja191_160` | volatility | close | 22 | sma((c<=delay(c,1)?std(c,20):0),20,1) |
| `gtja191_161` | volatility | close,high,low | 13 | mean(true_range,12) |
| `gtja191_162` | momentum | close | 24 | see body |
| `gtja191_163` | volume | open,high,low,close,volume,amount | 21 | rank(((-1*ret)*mean(v,20))*vwap*(high-close)) |
| `gtja191_164` | momentum | close,high,low | 20 | see body |
| `gtja191_165` | volatility | close | 142 | see body |
| `gtja191_166` | volatility | close | 40 | see body |
| `gtja191_167` | momentum | close | 13 | sum(max(0,c-delay(c,1)),12) |
| `gtja191_168` | volume | close,volume | 20 | -1*volume/mean(volume,20) |
| `gtja191_169` | momentum | close | 50 | see body |
| `gtja191_170` | volume | open,high,low,close,volume,amount | 21 | see body |
| `gtja191_171` | microstructure | open,high,low,close | 1 | -1*((l-c)*(o^5))/((c-h)*(c^5)) |
| `gtja191_172` | momentum | close,high,low | 20 | see body |
| `gtja191_173` | momentum | close | 40 | 3*sma(c,13,2)-2*sma(sma(c,13,2),13,2)+sma(sma(sma(log(c),13, |
| `gtja191_174` | volatility | close | 22 | sma((c>delay(c,1)?std(c,20):0),20,1) |
| `gtja191_175` | volatility | close,high,low | 7 | mean(true_range,6) |
| `gtja191_176` | volume | open,high,low,close,volume | 18 | see body |
| `gtja191_177` | momentum | close,high | 20 | ((20-highday(h,20))/20)*100 |
| `gtja191_178` | momentum,volume | close,volume | 2 | (c-delay(c,1))/delay(c,1)*v |
| `gtja191_179` | volume | open,high,low,close,volume,amount | 62 | rank(corr(vwap,v,4))*rank(corr(rank(low),rank(mean(v,50)),12 |
| `gtja191_180` | volume,reversal | close,volume | 67 | see body |
| `gtja191_181` | volatility | close | 40 | see body |
| `gtja191_182` | momentum | open,high,low,close,volume | 21 | see body |
| `gtja191_183` | volatility | close | 70 | see body |
| `gtja191_184` | reversal | open,close | 202 | see body |
| `gtja191_185` | reversal | open,close | 1 | rank(-1*(1-open/close)^2) |
| `gtja191_186` | momentum | close,high,low | 27 | see body (alpha172 averaged with its 6-day lag) |
| `gtja191_187` | reversal | open,high | 21 | see body |
| `gtja191_188` | volatility | close,high,low | 13 | (h-l-sma(h-l,11,2))/sma(h-l,11,2)*100 |
| `gtja191_189` | volatility | close | 12 | mean(abs(c-mean(c,6)),6) |
| `gtja191_190` | momentum | close | 39 | see body |
| `gtja191_191` | volume | open,high,low,close,volume | 25 | see body |

## qlib158 (154)

| id | theme | columns | warmup | formula |
|----|-------|---------|-------:|---------|
| `qlib158_beta10` | momentum | close | 10 | (\\mathrm{close}_t - \\mathrm{close}_{{t-10}}) / (10\\,\\mat |
| `qlib158_beta20` | momentum | close | 20 | (\\mathrm{close}_t - \\mathrm{close}_{{t-20}}) / (20\\,\\mat |
| `qlib158_beta30` | momentum | close | 30 | (\\mathrm{close}_t - \\mathrm{close}_{{t-30}}) / (30\\,\\mat |
| `qlib158_beta5` | momentum | close | 5 | (\\mathrm{close}_t - \\mathrm{close}_{{t-5}}) / (5\\,\\mathr |
| `qlib158_beta60` | momentum | close | 60 | (\\mathrm{close}_t - \\mathrm{close}_{{t-60}}) / (60\\,\\mat |
| `qlib158_cntd10` | reversal | close | 10 | \\mathrm{CNTP}_10 - \\mathrm{CNTN}_10 |
| `qlib158_cntd20` | reversal | close | 20 | \\mathrm{CNTP}_20 - \\mathrm{CNTN}_20 |
| `qlib158_cntd30` | reversal | close | 30 | \\mathrm{CNTP}_30 - \\mathrm{CNTN}_30 |
| `qlib158_cntd5` | reversal | close | 5 | \\mathrm{CNTP}_5 - \\mathrm{CNTN}_5 |
| `qlib158_cntd60` | reversal | close | 60 | \\mathrm{CNTP}_60 - \\mathrm{CNTN}_60 |
| `qlib158_cntn10` | reversal | close | 10 | \\mathrm{rolling\\_mean}(\\mathrm{1}[\\mathrm{close}<\\mathr |
| `qlib158_cntn20` | reversal | close | 20 | \\mathrm{rolling\\_mean}(\\mathrm{1}[\\mathrm{close}<\\mathr |
| `qlib158_cntn30` | reversal | close | 30 | \\mathrm{rolling\\_mean}(\\mathrm{1}[\\mathrm{close}<\\mathr |
| `qlib158_cntn5` | reversal | close | 5 | \\mathrm{rolling\\_mean}(\\mathrm{1}[\\mathrm{close}<\\mathr |
| `qlib158_cntn60` | reversal | close | 60 | \\mathrm{rolling\\_mean}(\\mathrm{1}[\\mathrm{close}<\\mathr |
| `qlib158_cntp10` | reversal | close | 10 | \\mathrm{rolling\\_mean}(\\mathrm{1}[\\mathrm{close}>\\mathr |
| `qlib158_cntp20` | reversal | close | 20 | \\mathrm{rolling\\_mean}(\\mathrm{1}[\\mathrm{close}>\\mathr |
| `qlib158_cntp30` | reversal | close | 30 | \\mathrm{rolling\\_mean}(\\mathrm{1}[\\mathrm{close}>\\mathr |
| `qlib158_cntp5` | reversal | close | 5 | \\mathrm{rolling\\_mean}(\\mathrm{1}[\\mathrm{close}>\\mathr |
| `qlib158_cntp60` | reversal | close | 60 | \\mathrm{rolling\\_mean}(\\mathrm{1}[\\mathrm{close}>\\mathr |
| `qlib158_cord10` | volume,microstructure | close,volume | 10 | \\mathrm{ts\\_corr}(\\mathrm{close}/\\mathrm{close}_{{-1}},  |
| `qlib158_cord20` | volume,microstructure | close,volume | 20 | \\mathrm{ts\\_corr}(\\mathrm{close}/\\mathrm{close}_{{-1}},  |
| `qlib158_cord30` | volume,microstructure | close,volume | 30 | \\mathrm{ts\\_corr}(\\mathrm{close}/\\mathrm{close}_{{-1}},  |
| `qlib158_cord5` | volume,microstructure | close,volume | 5 | \\mathrm{ts\\_corr}(\\mathrm{close}/\\mathrm{close}_{{-1}},  |
| `qlib158_cord60` | volume,microstructure | close,volume | 60 | \\mathrm{ts\\_corr}(\\mathrm{close}/\\mathrm{close}_{{-1}},  |
| `qlib158_corr10` | volume,microstructure | close,volume | 10 | \\mathrm{ts\\_corr}(\\mathrm{close}, \\log(\\mathrm{volume}+ |
| `qlib158_corr20` | volume,microstructure | close,volume | 20 | \\mathrm{ts\\_corr}(\\mathrm{close}, \\log(\\mathrm{volume}+ |
| `qlib158_corr30` | volume,microstructure | close,volume | 30 | \\mathrm{ts\\_corr}(\\mathrm{close}, \\log(\\mathrm{volume}+ |
| `qlib158_corr5` | volume,microstructure | close,volume | 5 | \\mathrm{ts\\_corr}(\\mathrm{close}, \\log(\\mathrm{volume}+ |
| `qlib158_corr60` | volume,microstructure | close,volume | 60 | \\mathrm{ts\\_corr}(\\mathrm{close}, \\log(\\mathrm{volume}+ |
| `qlib158_imax10` | momentum | high | 10 | \\mathrm{ts\\_argmax}(\\mathrm{high}, 10) / 10 |
| `qlib158_imax20` | momentum | high | 20 | \\mathrm{ts\\_argmax}(\\mathrm{high}, 20) / 20 |
| `qlib158_imax30` | momentum | high | 30 | \\mathrm{ts\\_argmax}(\\mathrm{high}, 30) / 30 |
| `qlib158_imax5` | momentum | high | 5 | \\mathrm{ts\\_argmax}(\\mathrm{high}, 5) / 5 |
| `qlib158_imax60` | momentum | high | 60 | \\mathrm{ts\\_argmax}(\\mathrm{high}, 60) / 60 |
| `qlib158_imin10` | momentum | low | 10 | \\mathrm{ts\\_argmin}(\\mathrm{low}, 10) / 10 |
| `qlib158_imin20` | momentum | low | 20 | \\mathrm{ts\\_argmin}(\\mathrm{low}, 20) / 20 |
| `qlib158_imin30` | momentum | low | 30 | \\mathrm{ts\\_argmin}(\\mathrm{low}, 30) / 30 |
| `qlib158_imin5` | momentum | low | 5 | \\mathrm{ts\\_argmin}(\\mathrm{low}, 5) / 5 |
| `qlib158_imin60` | momentum | low | 60 | \\mathrm{ts\\_argmin}(\\mathrm{low}, 60) / 60 |
| `qlib158_imxd10` | momentum | high,low | 10 | (\\mathrm{ts\\_argmax}(\\mathrm{high}, 10) - \\mathrm{ts\\_a |
| `qlib158_imxd20` | momentum | high,low | 20 | (\\mathrm{ts\\_argmax}(\\mathrm{high}, 20) - \\mathrm{ts\\_a |
| `qlib158_imxd30` | momentum | high,low | 30 | (\\mathrm{ts\\_argmax}(\\mathrm{high}, 30) - \\mathrm{ts\\_a |
| `qlib158_imxd5` | momentum | high,low | 5 | (\\mathrm{ts\\_argmax}(\\mathrm{high}, 5) - \\mathrm{ts\\_ar |
| `qlib158_imxd60` | momentum | high,low | 60 | (\\mathrm{ts\\_argmax}(\\mathrm{high}, 60) - \\mathrm{ts\\_a |
| `qlib158_klen` | microstructure | open,high,low | 1 | (\\mathrm{high} - \\mathrm{low}) / \\mathrm{open} |
| `qlib158_klow` | microstructure | open,low,close | 1 | (\\min(\\mathrm{open}, \\mathrm{close}) - \\mathrm{low}) / \ |
| `qlib158_klow2` | microstructure | open,high,low,close | 1 | (\\min(\\mathrm{open}, \\mathrm{close}) - \\mathrm{low}) / ( |
| `qlib158_kmid` | microstructure | open,close | 1 | (\\mathrm{close} - \\mathrm{open}) / \\mathrm{open} |
| `qlib158_kmid2` | microstructure | open,high,low,close | 1 | (\\mathrm{close} - \\mathrm{open}) / (\\mathrm{high} - \\mat |
| `qlib158_ksft` | microstructure | open,high,low,close | 1 | (2\\,\\mathrm{close} - \\mathrm{high} - \\mathrm{low}) / \\m |
| `qlib158_ksft2` | microstructure | open,high,low,close | 1 | (2\\,\\mathrm{close} - \\mathrm{high} - \\mathrm{low}) / (\\ |
| `qlib158_kup` | microstructure | open,high,close | 1 | (\\mathrm{high} - \\max(\\mathrm{open}, \\mathrm{close})) /  |
| `qlib158_kup2` | microstructure | open,high,low,close | 1 | (\\mathrm{high} - \\max(\\mathrm{open}, \\mathrm{close})) /  |
| `qlib158_ma10` | momentum | close | 10 | \\mathrm{ts\\_mean}(\\mathrm{close}, 10) / \\mathrm{close} |
| `qlib158_ma20` | momentum | close | 20 | \\mathrm{ts\\_mean}(\\mathrm{close}, 20) / \\mathrm{close} |
| `qlib158_ma30` | momentum | close | 30 | \\mathrm{ts\\_mean}(\\mathrm{close}, 30) / \\mathrm{close} |
| `qlib158_ma5` | momentum | close | 5 | \\mathrm{ts\\_mean}(\\mathrm{close}, 5) / \\mathrm{close} |
| `qlib158_ma60` | momentum | close | 60 | \\mathrm{ts\\_mean}(\\mathrm{close}, 60) / \\mathrm{close} |
| `qlib158_max10` | momentum | high,close | 10 | \\mathrm{ts\\_max}(\\mathrm{high}, 10) / \\mathrm{close} |
| `qlib158_max20` | momentum | high,close | 20 | \\mathrm{ts\\_max}(\\mathrm{high}, 20) / \\mathrm{close} |
| `qlib158_max30` | momentum | high,close | 30 | \\mathrm{ts\\_max}(\\mathrm{high}, 30) / \\mathrm{close} |
| `qlib158_max5` | momentum | high,close | 5 | \\mathrm{ts\\_max}(\\mathrm{high}, 5) / \\mathrm{close} |
| `qlib158_max60` | momentum | high,close | 60 | \\mathrm{ts\\_max}(\\mathrm{high}, 60) / \\mathrm{close} |
| `qlib158_min10` | momentum | low,close | 10 | \\mathrm{ts\\_min}(\\mathrm{low}, 10) / \\mathrm{close} |
| `qlib158_min20` | momentum | low,close | 20 | \\mathrm{ts\\_min}(\\mathrm{low}, 20) / \\mathrm{close} |
| `qlib158_min30` | momentum | low,close | 30 | \\mathrm{ts\\_min}(\\mathrm{low}, 30) / \\mathrm{close} |
| `qlib158_min5` | momentum | low,close | 5 | \\mathrm{ts\\_min}(\\mathrm{low}, 5) / \\mathrm{close} |
| `qlib158_min60` | momentum | low,close | 60 | \\mathrm{ts\\_min}(\\mathrm{low}, 60) / \\mathrm{close} |
| `qlib158_qtld10` | momentum | close | 10 | \\mathrm{quantile}_{{0.2}}(\\mathrm{close}, 10) / \\mathrm{c |
| `qlib158_qtld20` | momentum | close | 20 | \\mathrm{quantile}_{{0.2}}(\\mathrm{close}, 20) / \\mathrm{c |
| `qlib158_qtld30` | momentum | close | 30 | \\mathrm{quantile}_{{0.2}}(\\mathrm{close}, 30) / \\mathrm{c |
| `qlib158_qtld5` | momentum | close | 5 | \\mathrm{quantile}_{{0.2}}(\\mathrm{close}, 5) / \\mathrm{cl |
| `qlib158_qtld60` | momentum | close | 60 | \\mathrm{quantile}_{{0.2}}(\\mathrm{close}, 60) / \\mathrm{c |
| `qlib158_qtlu10` | momentum | close | 10 | \\mathrm{quantile}_{{0.8}}(\\mathrm{close}, 10) / \\mathrm{c |
| `qlib158_qtlu20` | momentum | close | 20 | \\mathrm{quantile}_{{0.8}}(\\mathrm{close}, 20) / \\mathrm{c |
| `qlib158_qtlu30` | momentum | close | 30 | \\mathrm{quantile}_{{0.8}}(\\mathrm{close}, 30) / \\mathrm{c |
| `qlib158_qtlu5` | momentum | close | 5 | \\mathrm{quantile}_{{0.8}}(\\mathrm{close}, 5) / \\mathrm{cl |
| `qlib158_qtlu60` | momentum | close | 60 | \\mathrm{quantile}_{{0.8}}(\\mathrm{close}, 60) / \\mathrm{c |
| `qlib158_rank10` | momentum | close | 10 | \\mathrm{ts\\_rank}(\\mathrm{close}, 10) |
| `qlib158_rank20` | momentum | close | 20 | \\mathrm{ts\\_rank}(\\mathrm{close}, 20) |
| `qlib158_rank30` | momentum | close | 30 | \\mathrm{ts\\_rank}(\\mathrm{close}, 30) |
| `qlib158_rank5` | momentum | close | 5 | \\mathrm{ts\\_rank}(\\mathrm{close}, 5) |
| `qlib158_rank60` | momentum | close | 60 | \\mathrm{ts\\_rank}(\\mathrm{close}, 60) |
| `qlib158_resi10` | momentum | close | 10 | (\\mathrm{close} - \\mathrm{ts\\_mean}(\\mathrm{close}, 10)) |
| `qlib158_resi20` | momentum | close | 20 | (\\mathrm{close} - \\mathrm{ts\\_mean}(\\mathrm{close}, 20)) |
| `qlib158_resi30` | momentum | close | 30 | (\\mathrm{close} - \\mathrm{ts\\_mean}(\\mathrm{close}, 30)) |
| `qlib158_resi5` | momentum | close | 5 | (\\mathrm{close} - \\mathrm{ts\\_mean}(\\mathrm{close}, 5))  |
| `qlib158_resi60` | momentum | close | 60 | (\\mathrm{close} - \\mathrm{ts\\_mean}(\\mathrm{close}, 60)) |
| `qlib158_roc10` | momentum | close | 10 | \\mathrm{close}_t / \\mathrm{close}_{{t-10}} - 1 |
| `qlib158_roc20` | momentum | close | 20 | \\mathrm{close}_t / \\mathrm{close}_{{t-20}} - 1 |
| `qlib158_roc30` | momentum | close | 30 | \\mathrm{close}_t / \\mathrm{close}_{{t-30}} - 1 |
| `qlib158_roc5` | momentum | close | 5 | \\mathrm{close}_t / \\mathrm{close}_{{t-5}} - 1 |
| `qlib158_roc60` | momentum | close | 60 | \\mathrm{close}_t / \\mathrm{close}_{{t-60}} - 1 |
| `qlib158_rsqr10` | momentum | close | 10 | \\mathrm{ts\\_corr}(\\mathrm{close}, t, 10)^2 |
| `qlib158_rsqr20` | momentum | close | 20 | \\mathrm{ts\\_corr}(\\mathrm{close}, t, 20)^2 |
| `qlib158_rsqr30` | momentum | close | 30 | \\mathrm{ts\\_corr}(\\mathrm{close}, t, 30)^2 |
| `qlib158_rsqr5` | momentum | close | 5 | \\mathrm{ts\\_corr}(\\mathrm{close}, t, 5)^2 |
| `qlib158_rsqr60` | momentum | close | 60 | \\mathrm{ts\\_corr}(\\mathrm{close}, t, 60)^2 |
| `qlib158_rsv10` | momentum | high,low,close | 10 | (\\mathrm{close} - \\mathrm{ts\\_min}(\\mathrm{low}, 10)) /  |
| `qlib158_rsv20` | momentum | high,low,close | 20 | (\\mathrm{close} - \\mathrm{ts\\_min}(\\mathrm{low}, 20)) /  |
| `qlib158_rsv30` | momentum | high,low,close | 30 | (\\mathrm{close} - \\mathrm{ts\\_min}(\\mathrm{low}, 30)) /  |
| `qlib158_rsv5` | momentum | high,low,close | 5 | (\\mathrm{close} - \\mathrm{ts\\_min}(\\mathrm{low}, 5)) / ( |
| `qlib158_rsv60` | momentum | high,low,close | 60 | (\\mathrm{close} - \\mathrm{ts\\_min}(\\mathrm{low}, 60)) /  |
| `qlib158_std10` | momentum | close | 10 | \\mathrm{ts\\_std}(\\mathrm{close}, 10) / \\mathrm{close} |
| `qlib158_std20` | momentum | close | 20 | \\mathrm{ts\\_std}(\\mathrm{close}, 20) / \\mathrm{close} |
| `qlib158_std30` | momentum | close | 30 | \\mathrm{ts\\_std}(\\mathrm{close}, 30) / \\mathrm{close} |
| `qlib158_std5` | momentum | close | 5 | \\mathrm{ts\\_std}(\\mathrm{close}, 5) / \\mathrm{close} |
| `qlib158_std60` | momentum | close | 60 | \\mathrm{ts\\_std}(\\mathrm{close}, 60) / \\mathrm{close} |
| `qlib158_sumd10` | reversal | close | 10 | \\mathrm{SUMP}_w - \\mathrm{SUMN}_w |
| `qlib158_sumd20` | reversal | close | 20 | \\mathrm{SUMP}_w - \\mathrm{SUMN}_w |
| `qlib158_sumd30` | reversal | close | 30 | \\mathrm{SUMP}_w - \\mathrm{SUMN}_w |
| `qlib158_sumd5` | reversal | close | 5 | \\mathrm{SUMP}_w - \\mathrm{SUMN}_w |
| `qlib158_sumd60` | reversal | close | 60 | \\mathrm{SUMP}_w - \\mathrm{SUMN}_w |
| `qlib158_sumn10` | reversal | close | 10 | \\sum \\max(-\\Delta\\mathrm{close}, 0) / \\sum /\\Delta\\ma |
| `qlib158_sumn20` | reversal | close | 20 | \\sum \\max(-\\Delta\\mathrm{close}, 0) / \\sum /\\Delta\\ma |
| `qlib158_sumn30` | reversal | close | 30 | \\sum \\max(-\\Delta\\mathrm{close}, 0) / \\sum /\\Delta\\ma |
| `qlib158_sumn5` | reversal | close | 5 | \\sum \\max(-\\Delta\\mathrm{close}, 0) / \\sum /\\Delta\\ma |
| `qlib158_sumn60` | reversal | close | 60 | \\sum \\max(-\\Delta\\mathrm{close}, 0) / \\sum /\\Delta\\ma |
| `qlib158_sump10` | reversal | close | 10 | \\sum \\max(\\Delta\\mathrm{close}, 0) / \\sum /\\Delta\\mat |
| `qlib158_sump20` | reversal | close | 20 | \\sum \\max(\\Delta\\mathrm{close}, 0) / \\sum /\\Delta\\mat |
| `qlib158_sump30` | reversal | close | 30 | \\sum \\max(\\Delta\\mathrm{close}, 0) / \\sum /\\Delta\\mat |
| `qlib158_sump5` | reversal | close | 5 | \\sum \\max(\\Delta\\mathrm{close}, 0) / \\sum /\\Delta\\mat |
| `qlib158_sump60` | reversal | close | 60 | \\sum \\max(\\Delta\\mathrm{close}, 0) / \\sum /\\Delta\\mat |
| `qlib158_vma10` | volume,volatility | volume | 10 | \\mathrm{ts\\_mean}(\\mathrm{volume}, 10) / \\mathrm{volume} |
| `qlib158_vma20` | volume,volatility | volume | 20 | \\mathrm{ts\\_mean}(\\mathrm{volume}, 20) / \\mathrm{volume} |
| `qlib158_vma30` | volume,volatility | volume | 30 | \\mathrm{ts\\_mean}(\\mathrm{volume}, 30) / \\mathrm{volume} |
| `qlib158_vma5` | volume,volatility | volume | 5 | \\mathrm{ts\\_mean}(\\mathrm{volume}, 5) / \\mathrm{volume} |
| `qlib158_vma60` | volume,volatility | volume | 60 | \\mathrm{ts\\_mean}(\\mathrm{volume}, 60) / \\mathrm{volume} |
| `qlib158_vstd10` | volume,volatility | volume | 10 | \\mathrm{ts\\_std}(\\mathrm{volume}, 10) / \\mathrm{volume} |
| `qlib158_vstd20` | volume,volatility | volume | 20 | \\mathrm{ts\\_std}(\\mathrm{volume}, 20) / \\mathrm{volume} |
| `qlib158_vstd30` | volume,volatility | volume | 30 | \\mathrm{ts\\_std}(\\mathrm{volume}, 30) / \\mathrm{volume} |
| `qlib158_vstd5` | volume,volatility | volume | 5 | \\mathrm{ts\\_std}(\\mathrm{volume}, 5) / \\mathrm{volume} |
| `qlib158_vstd60` | volume,volatility | volume | 60 | \\mathrm{ts\\_std}(\\mathrm{volume}, 60) / \\mathrm{volume} |
| `qlib158_vsumd10` | volume,volatility | volume | 10 | \\mathrm{VSUMP}_w - \\mathrm{VSUMN}_w |
| `qlib158_vsumd20` | volume,volatility | volume | 20 | \\mathrm{VSUMP}_w - \\mathrm{VSUMN}_w |
| `qlib158_vsumd30` | volume,volatility | volume | 30 | \\mathrm{VSUMP}_w - \\mathrm{VSUMN}_w |
| `qlib158_vsumd5` | volume,volatility | volume | 5 | \\mathrm{VSUMP}_w - \\mathrm{VSUMN}_w |
| `qlib158_vsumd60` | volume,volatility | volume | 60 | \\mathrm{VSUMP}_w - \\mathrm{VSUMN}_w |
| `qlib158_vsumn10` | volume,volatility | volume | 10 | \\sum \\max(-\\Delta v, 0) / \\sum /\\Delta v/ |
| `qlib158_vsumn20` | volume,volatility | volume | 20 | \\sum \\max(-\\Delta v, 0) / \\sum /\\Delta v/ |
| `qlib158_vsumn30` | volume,volatility | volume | 30 | \\sum \\max(-\\Delta v, 0) / \\sum /\\Delta v/ |
| `qlib158_vsumn5` | volume,volatility | volume | 5 | \\sum \\max(-\\Delta v, 0) / \\sum /\\Delta v/ |
| `qlib158_vsumn60` | volume,volatility | volume | 60 | \\sum \\max(-\\Delta v, 0) / \\sum /\\Delta v/ |
| `qlib158_vsump10` | volume,volatility | volume | 10 | \\sum \\max(\\Delta v, 0) / \\sum /\\Delta v/ |
| `qlib158_vsump20` | volume,volatility | volume | 20 | \\sum \\max(\\Delta v, 0) / \\sum /\\Delta v/ |
| `qlib158_vsump30` | volume,volatility | volume | 30 | \\sum \\max(\\Delta v, 0) / \\sum /\\Delta v/ |
| `qlib158_vsump5` | volume,volatility | volume | 5 | \\sum \\max(\\Delta v, 0) / \\sum /\\Delta v/ |
| `qlib158_vsump60` | volume,volatility | volume | 60 | \\sum \\max(\\Delta v, 0) / \\sum /\\Delta v/ |
| `qlib158_wvma10` | volume,volatility | close,volume | 10 | \\mathrm{ts\\_std}(\\mathrm{ret}\\cdot v, 10) / \\mathrm{ts\ |
| `qlib158_wvma20` | volume,volatility | close,volume | 20 | \\mathrm{ts\\_std}(\\mathrm{ret}\\cdot v, 20) / \\mathrm{ts\ |
| `qlib158_wvma30` | volume,volatility | close,volume | 30 | \\mathrm{ts\\_std}(\\mathrm{ret}\\cdot v, 30) / \\mathrm{ts\ |
| `qlib158_wvma5` | volume,volatility | close,volume | 5 | \\mathrm{ts\\_std}(\\mathrm{ret}\\cdot v, 5) / \\mathrm{ts\\ |
| `qlib158_wvma60` | volume,volatility | close,volume | 60 | \\mathrm{ts\\_std}(\\mathrm{ret}\\cdot v, 60) / \\mathrm{ts\ |

# 15-minute energy consumption

The integration reads the portal's 15-minute consumption intervals and
combines each complete group of four into an hourly Home Assistant external
energy statistic. This preserves the kWh total while meeting Home Assistant's
hour-aligned long-term statistics requirement. Hours with missing intervals
are skipped, but later complete hours are still imported. The **Power consumption
(15min)** sensor still exposes the latest 15-minute value.

On the first successful update, the integration requests the full available
`Verbrauch` period. Later updates resume after the last complete hour. The
statistic ID is `oekostrom:consumption_15min_<account_id>`. The first update
after this statistics migration rebuilds the existing history from the portal
to correct earlier cumulative values. Later updates resume after the last
complete hour. Add the statistic as an energy source under
**Settings → Dashboards → Energy**. The cumulative sum is built from the
portal's interval kWh values, including repeated intervals during daylight
saving time.

The portal may not expose a consumption period for every account or at every
time. If the sensor has no value, check the integration logs and confirm that
the account has a `Verbrauch` settlement period. Statistics become available
after the first successful profile import and recorder processing.

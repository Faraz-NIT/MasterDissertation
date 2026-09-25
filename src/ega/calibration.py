"""Convert already-pooled, anonymized incident durations into transparent rate ranges."""
from __future__ import annotations
import pandas as pd
from scipy.stats import norm
from .disturbances import QUALITY_CLASSES
from .util import atomic_json

def calibrate(csv_path,exposure_days,provenance,output):
    if exposure_days<=0 or not provenance.strip():raise ValueError('Positive exposure days and calibration provenance are required')
    frame=pd.read_csv(csv_path)
    required={'failure_class','duration_days'}
    if not required<=set(frame):raise ValueError('Columns required: failure_class,duration_days. Supply only anonymized pooled records.')
    if set(frame)-required:raise ValueError('Remove retailer IDs, dates and other identifying columns before calibration')
    if not set(frame.failure_class)<=set(QUALITY_CLASSES):raise ValueError('Unknown failure class')
    if (frame.duration_days<1).any():raise ValueError('Incident durations must be positive')
    z=norm.ppf(0.975);classes={}
    for family,rows in frame.groupby('failure_class'):
        count=len(rows)
        if count>exposure_days:raise ValueError('More onsets than exposure days; review denominator')
        p=count/exposure_days;den=1+z*z/exposure_days
        center=(p+z*z/(2*exposure_days))/den
        width=z*((p*(1-p)/exposure_days+z*z/(4*exposure_days**2))**0.5)/den
        classes[family]={'onset_rate_range':[max(0,center-width),min(1,center+width)],
                         'duration_range':[int(rows.duration_days.min()),int(rows.duration_days.max())],
                         'onsets':count,'rare_event_only':count<3}
    result={'version':'pooled-calibration-v1','pooled_anonymized':True,'provenance':provenance,'exposure_days':exposure_days,
            'classes':classes,'limitations':'Marginal rates only. Co-occurrence and cause-specific exposure require additional calibration; isolated incidents should be stress scenarios.'}
    atomic_json(output,result);return result

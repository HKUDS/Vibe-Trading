import { TimeAxisLabelFormatterOption, TimeAxisLabelFormatterParsed } from './../coord/axisCommonTypes.js';
import { ScaleTick } from './types.js';
import { LocaleOption } from '../core/locale.js';
import Model from '../model/Model.js';
export declare const ONE_SECOND = 1000;
export declare const ONE_MINUTE: number;
export declare const ONE_HOUR: number;
export declare const ONE_DAY: number;
export declare const ONE_YEAR: number;
export declare const fullLeveledFormatter: {
    year: string;
    month: string;
    day: string;
    hour: string;
    minute: string;
    second: string;
    millisecond: string;
};
export declare type JSDateGetterNames = 'getUTCFullYear' | 'getFullYear' | 'getUTCMonth' | 'getMonth' | 'getUTCDate' | 'getDate' | 'getUTCHours' | 'getHours' | 'getUTCMinutes' | 'getMinutes' | 'getUTCSeconds' | 'getSeconds' | 'getUTCMilliseconds' | 'getMilliseconds';
export declare type JSDateSetterNames = 'setUTCFullYear' | 'setFullYear' | 'setUTCMonth' | 'setMonth' | 'setUTCDate' | 'setDate' | 'setUTCHours' | 'setHours' | 'setUTCMinutes' | 'setMinutes' | 'setUTCSeconds' | 'setSeconds' | 'setUTCMilliseconds' | 'setMilliseconds';
export declare type PrimaryTimeUnit = (typeof primaryTimeUnits)[number];
export declare type TimeUnit = (typeof timeUnits)[number];
export declare const primaryTimeUnits: readonly ["year", "month", "day", "hour", "minute", "second", "millisecond"];
export declare const timeUnits: readonly ["year", "half-year", "quarter", "month", "week", "half-week", "day", "half-day", "quarter-day", "hour", "minute", "second", "millisecond"];
export declare function parseTimeAxisLabelFormatter(formatter: TimeAxisLabelFormatterOption): TimeAxisLabelFormatterParsed;
export declare function pad(str: string | number, len: number): string;
export declare function getPrimaryTimeUnit(timeUnit: TimeUnit): PrimaryTimeUnit;
export declare function isPrimaryTimeUnit(timeUnit: TimeUnit): boolean;
export declare function getDefaultFormatPrecisionOfInterval(timeUnit: PrimaryTimeUnit): PrimaryTimeUnit;
export declare function format(time: unknown, template: string, isUTC: boolean, lang?: string | Model<LocaleOption>): string;
export declare function leveledFormat(tick: ScaleTick, idx: number, formatter: TimeAxisLabelFormatterParsed, lang: string | Model<LocaleOption>, isUTC: boolean): string;
export declare function getUnitFromValue(value: number | string | Date, isUTC: boolean): PrimaryTimeUnit;
/**
 * e.g.,
 * If timeUnit is 'year', return the Jan 1st 00:00:00 000 of that year.
 * If timeUnit is 'day', return the 00:00:00 000 of that day.
 *
 * @return The input date.
 */
export declare function roundTime(date: Date, timeUnit: PrimaryTimeUnit, isUTC: boolean): Date;
export declare function fullYearGetterName(isUTC: boolean): "getUTCFullYear" | "getFullYear";
export declare function monthGetterName(isUTC: boolean): "getUTCMonth" | "getMonth";
export declare function dateGetterName(isUTC: boolean): "getUTCDate" | "getDate";
export declare function hoursGetterName(isUTC: boolean): "getUTCHours" | "getHours";
export declare function minutesGetterName(isUTC: boolean): "getUTCMinutes" | "getMinutes";
export declare function secondsGetterName(isUTC: boolean): "getUTCSeconds" | "getSeconds";
export declare function millisecondsGetterName(isUTC: boolean): "getUTCMilliseconds" | "getMilliseconds";
export declare function fullYearSetterName(isUTC: boolean): "setUTCFullYear" | "setFullYear";
export declare function monthSetterName(isUTC: boolean): "setUTCMonth" | "setMonth";
export declare function dateSetterName(isUTC: boolean): "setUTCDate" | "setDate";
export declare function hoursSetterName(isUTC: boolean): "setUTCHours" | "setHours";
export declare function minutesSetterName(isUTC: boolean): "setUTCMinutes" | "setMinutes";
export declare function secondsSetterName(isUTC: boolean): "setUTCSeconds" | "setSeconds";
export declare function millisecondsSetterName(isUTC: boolean): "setUTCMilliseconds" | "setMilliseconds";

import IntervalScale from '../scale/Interval.js';
import LogScale from '../scale/Log.js';
import type Axis from './Axis.js';
/**
 * NOTE: See the summary of the process of extent determination in the comment of `scaleMapper.setExtent`.
 *
 * @see SCALE_EXTENT_CONSTRUCTION for the full processing flow.
 */
export declare function scaleCalcAlign(targetAxis: Axis, alignToScale: IntervalScale | LogScale): void;

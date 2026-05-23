import { EChartsType } from './echarts.js';
import type { CoordinateSystemMaster } from '../coord/CoordinateSystem.js';
import type Element from 'zrender/lib/Element.js';
import type ComponentModel from '../model/Component.js';
import type ComponentView from '../view/Component.js';
import type ChartView from '../view/Chart.js';
import type SeriesModel from '../model/Series.js';
import type GlobalModel from '../model/Global.js';
declare const availableMethods: (keyof EChartsType)[];
interface ExtensionAPI extends Pick<EChartsType, (typeof availableMethods)[number]> {
}
declare abstract class ExtensionAPI {
    constructor(ecInstance: EChartsType);
    abstract getCoordinateSystems(): CoordinateSystemMaster[];
    abstract getComponentByElement(el: Element): ComponentModel;
    abstract enterEmphasis(el: Element, highlightDigit?: number): void;
    abstract leaveEmphasis(el: Element, highlightDigit?: number): void;
    abstract enterSelect(el: Element): void;
    abstract leaveSelect(el: Element): void;
    abstract enterBlur(el: Element): void;
    abstract leaveBlur(el: Element): void;
    abstract getViewOfComponentModel(componentModel: ComponentModel): ComponentView;
    abstract getViewOfSeriesModel(seriesModel: SeriesModel): ChartView;
    abstract getModel(): GlobalModel;
    abstract getECUpdateCycleVersion(): number;
    /**
     * PENDING: a temporary method - may be refactored.
     * Whether a "threshold hoverLayer" is used.
     * `true` means using hover layer due to over `hoverLayerThreshold`.
     * Otherwise, if `false`, hover layer may be still used due to progressive (incremental),
     * but this method does not need to cover this case.
     */
    abstract usingTHL(): boolean;
}
export declare function getViewOfComponentOrSeries(api: ExtensionAPI, componentOrSeries: ComponentModel): ChartView | ComponentView;
export default ExtensionAPI;

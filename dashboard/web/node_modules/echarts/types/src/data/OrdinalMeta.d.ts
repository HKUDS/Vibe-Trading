import Model from '../model/Model.js';
import { OrdinalNumber, OrdinalRawValue } from '../util/types.js';
declare class OrdinalMeta {
    readonly categories: OrdinalRawValue[];
    private _needCollect;
    private _deduplication;
    private _map;
    private _onCollect;
    readonly uid: number;
    /**
     * PENDING - Regarding forcibly converting to string:
     *  In the early days, the underlying hash map impl used JS plain object and converted the key to
     *  string; later in https://github.com/ecomfe/zrender/pull/966 it was changed to a JS Map (in supported
     *  platforms), which does not require string keys. But consider any input that `scale/Ordinal['parse']`
     *  is involved, a number input represents an `OrdinalNumber` (i.e., an index), and affect the query
     *  behavior:
     *    - If forcbily converting to string:
     *      pros: users can use numeric string (such as, '123') to query the raw data (123), tho it's probably
     *      still confusing.
     *      cons: NaN/null/undefined in data will be equals to 'NaN'/'null'/'undefined', if simply using
     *      `val + ''` to convert them, like currently `getName` does.
     *    - Otherwise:
     *      pros: see NaN/null/undefined case above.
     *      cons: users cannot query the raw data (123) any more.
     *  There are two inconsistent behaviors in the current impl:
     *    - Force conversion is applied on the case `xAxis{data: ['aaa', 'bbb', ...]}`,
     *      but no conversion applied to the case `xAxis{data: [{value: 'aaa'}, ...]}` and
     *      the case `dataset: {source: [['aaa', 123], ['bbb', 234], ...]}`.
     *    - behaves differently according to whether JS Map is supported (the polyfill is simply using JS
     *      plain object) (tho it seems rare platform that do not support it).
     *  Since there's no sufficient good solution to offset cost of the breaking change, we preserve the
     *  current behavior, until real issues is reported.
     */
    constructor(opt: {
        categories?: OrdinalRawValue[];
        needCollect?: boolean;
        deduplication?: boolean;
        onCollect?: OrdinalMeta['_onCollect'];
    });
    static createByAxisModel(axisModel: Model): OrdinalMeta;
    getOrdinal(category: OrdinalRawValue): OrdinalNumber;
    /**
     * @return The ordinal. If not found, return NaN.
     */
    parseAndCollect(category: OrdinalRawValue | OrdinalNumber): OrdinalNumber;
    private _getOrCreateMap;
}
export default OrdinalMeta;

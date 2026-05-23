import GlobalModel from '../model/Global.js';
export declare type GlobalModelCachePerECPrepare = {
    __: 'prepare';
};
export declare type GlobalModelCachePerECFullUpdate = {
    __: 'fullUpdate';
};
/**
 * CAVEAT: Can only be called by `echarts.ts`
 */
export declare function resetCachePerECPrepare(ecModel: GlobalModel): void;
/**
 * CAVEAT: Can only be called by `echarts.ts`
 */
export declare function resetCachePerECFullUpdate(ecModel: GlobalModel): void;
/**
 * The cache is auto cleared at the beginning of EC_PREPARE.
 * See also comments in EC_CYCLE.
 *
 * NOTICE:
 *  - EC_PREPARE is not necessarily executed before each EC_FULL_UPDATE performing.
 *    Typically, `setOption` trigger EC_PREPARE, but `dispatchAction` does not.
 *  - It is not cleared in EC_PARTIAL_UPDATE and EC_PROGRESSIVE_CYCLE.
 *
 */
export declare function getCachePerECPrepare(ecModel: GlobalModel): GlobalModelCachePerECPrepare;
/**
 * @usage
 *  ```js
 *  const cycleCache = makeInner<{
 *      prop1: number;
 *      prop2: string;
 *  }, GlobalModelCachePerECFullUpdate>();
 *  function doSomthing(ecModel: GlobalModel): void {
 *      cycleCache(getCachePerECFullUpdate(ecModel)).prop1 = 123;
 *      cycleCache(getCachePerECFullUpdate(ecModel)).prop2;
 *  }
 *  ```
 *
 * The cache is auto cleared at the beginning of EC_FULL_UPDATE.
 * See also comments in EC_CYCLE.
 *
 * NOTICE:
 *  - It is not cleared in EC_PARTIAL_UPDATE and EC_PROGRESSIVE_CYCLE.
 *  - The cache should NOT be written before EC_FULL_UPDATE started, such as:
 *      - should NOT in `getTargetSeries` methods of data processors.
 *      - should NOT in `init`/`mergeOption`/`optionUpdated`/`getData` methods of component/series models.
 *  - See `getCachePerECPrepare` for details.
 */
export declare function getCachePerECFullUpdate(ecModel: GlobalModel): GlobalModelCachePerECFullUpdate;

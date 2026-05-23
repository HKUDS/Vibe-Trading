
/*
* Licensed to the Apache Software Foundation (ASF) under one
* or more contributor license agreements.  See the NOTICE file
* distributed with this work for additional information
* regarding copyright ownership.  The ASF licenses this file
* to you under the Apache License, Version 2.0 (the
* "License"); you may not use this file except in compliance
* with the License.  You may obtain a copy of the License at
*
*   http://www.apache.org/licenses/LICENSE-2.0
*
* Unless required by applicable law or agreed to in writing,
* software distributed under the License is distributed on an
* "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
* KIND, either express or implied.  See the License for the
* specific language governing permissions and limitations
* under the License.
*/


/**
 * AUTO-GENERATED FILE. DO NOT MODIFY.
 */

/*
* Licensed to the Apache Software Foundation (ASF) under one
* or more contributor license agreements.  See the NOTICE file
* distributed with this work for additional information
* regarding copyright ownership.  The ASF licenses this file
* to you under the Apache License, Version 2.0 (the
* "License"); you may not use this file except in compliance
* with the License.  You may obtain a copy of the License at
*
*   http://www.apache.org/licenses/LICENSE-2.0
*
* Unless required by applicable law or agreed to in writing,
* software distributed under the License is distributed on an
* "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
* KIND, either express or implied.  See the License for the
* specific language governing permissions and limitations
* under the License.
*/
import { __extends } from "tslib";
import * as zrUtil from 'zrender/lib/core/util.js';
import Model from './Model.js';
import * as componentUtil from '../util/component.js';
import { enableClassManagement, parseClassType, isExtendedClass, mountExtend } from '../util/clazz.js';
import { makeInner, queryReferringComponents } from '../util/model.js';
import * as layout from '../util/layout.js';
var inner = makeInner();
var ComponentModel = /** @class */function (_super) {
  __extends(ComponentModel, _super);
  function ComponentModel(option, parentModel, ecModel) {
    var _this = _super.call(this, option, parentModel, ecModel) || this;
    _this.uid = componentUtil.getUID('ec_cpt_model');
    return _this;
  }
  ComponentModel.prototype.init = function (option, parentModel, ecModel) {
    this.mergeDefaultAndTheme(option, ecModel);
  };
  ComponentModel.prototype.mergeDefaultAndTheme = function (option, ecModel) {
    var layoutMode = layout.fetchLayoutMode(this);
    var inputPositionParams = layoutMode ? layout.getLayoutParams(option) : {};
    var themeModel = ecModel.getTheme();
    zrUtil.merge(option, themeModel.get(this.mainType));
    zrUtil.merge(option, this.getDefaultOption());
    if (layoutMode) {
      layout.mergeLayoutParam(option, inputPositionParams, layoutMode);
    }
  };
  ComponentModel.prototype.mergeOption = function (option, ecModel) {
    zrUtil.merge(this.option, option, true);
    var layoutMode = layout.fetchLayoutMode(this);
    if (layoutMode) {
      layout.mergeLayoutParam(this.option, option, layoutMode);
    }
  };
  /**
   * Called immediately after `init` or `mergeOption` of this instance called.
   */
  ComponentModel.prototype.optionUpdated = function (newCptOption, isInit) {
    // MUST NOT do anything here.
  };
  /**
   * [How to declare defaultOption]:
   *
   * (A) If using class declaration in typescript (since echarts 5):
   * ```ts
   * import {ComponentOption} from '../model/option.js';
   * export interface XxxOption extends ComponentOption {
   *     aaa: number
   * }
   * export class XxxModel extends Component {
   *     static type = 'xxx';
   *     static defaultOption: XxxOption = {
   *         aaa: 123
   *     }
   * }
   * Component.registerClass(XxxModel);
   * ```
   * ```ts
   * import {inheritDefaultOption} from '../util/component.js';
   * import {XxxModel, XxxOption} from './XxxModel.js';
   * export interface XxxSubOption extends XxxOption {
   *     bbb: number
   * }
   * class XxxSubModel extends XxxModel {
   *     static defaultOption: XxxSubOption = inheritDefaultOption(XxxModel.defaultOption, {
   *         bbb: 456
   *     })
   *     fn() {
   *         let opt = this.getDefaultOption();
   *         // opt is {aaa: 123, bbb: 456}
   *     }
   * }
   * ```
   *
   * (B) If using class extend (previous approach in echarts 3 & 4):
   * ```js
   * let XxxComponent = Component.extend({
   *     defaultOption: {
   *         xx: 123
   *     }
   * })
   * ```
   * ```js
   * let XxxSubComponent = XxxComponent.extend({
   *     defaultOption: {
   *         yy: 456
   *     },
   *     fn: function () {
   *         let opt = this.getDefaultOption();
   *         // opt is {xx: 123, yy: 456}
   *     }
   * })
   * ```
   */
  ComponentModel.prototype.getDefaultOption = function () {
    var ctor = this.constructor;
    if (!isExtendedClass(ctor)) {
      // When using ES class declaration, defaultOption must be declared as static.
      // And manually inherit the defaultOption from its parent class if needed, such as,
      //  ```ts
      //  static defaultOption = inheritDefaultOption(ParentModel.defaultOption, {...});
      //  ```
      return ctor.defaultOption;
    }
    // FIXME: remove this approach?
    // Legacy: auto merge defaultOption from ancestor classes if using ParentClass.extend(subProto)
    var fields = inner(this);
    if (!fields.defaultOption) {
      var optList = [];
      var clz = ctor;
      while (clz) {
        var opt = clz.prototype.defaultOption;
        opt && optList.push(opt);
        clz = clz.superClass;
      }
      var defaultOption = {};
      for (var i = optList.length - 1; i >= 0; i--) {
        defaultOption = zrUtil.merge(defaultOption, optList[i], true);
      }
      fields.defaultOption = defaultOption;
    }
    return fields.defaultOption;
  };
  /**
   * Notice: always force to input param `useDefault` in case that forget to consider it.
   * The same behavior as `modelUtil.parseFinder`.
   *
   * @param useDefault In many cases like series refer axis and axis refer grid,
   *        If axis index / axis id not specified, use the first target as default.
   *        In other cases like dataZoom refer axis, if not specified, measn no refer.
   */
  ComponentModel.prototype.getReferringComponents = function (mainType, opt) {
    var indexKey = mainType + 'Index';
    var idKey = mainType + 'Id';
    return queryReferringComponents(this.ecModel, mainType, {
      index: this.get(indexKey, true),
      id: this.get(idKey, true)
    }, opt);
  };
  ComponentModel.prototype.getBoxLayoutParams = function () {
    // Consider itself having box layout configs.
    // For backward compatibility, by default do not `ignoreParent`.
    return layout.getBoxLayoutParams(this, false);
  };
  /**
   * If developers don't configure zlevel. We will assign zlevel to series based on the key, if provided.
   * For example, lines with trail effect is expected to be in an individual zlevel.
   *
   * @tutorial [GET_ZLEVEL_KEY_FOR_PROGRESSIVE]
   * Regarding "progressive rendering", zrender can automatically assign a dedicated "incremental layer"
   * for `el.incremental` per zlevel. But there is a trade-off:
   *  - If we do not provide different zlevelKey for different series here, all incremental elements from
   *    different series will be assigned to one incremental layer, which causes them to cover each other
   *    in an order depending on progressive steps.
   *      i.e., seriesA_el1 -covered_by-> seriesB_el1 -covered_by-> seriesC_el1 -> seriesA_el2 -> seriesB_el2 ...
   *    This order may causes an unexpected visual result: series with small data are likely to be completely
   *    covered by series with large data. (like in test/scatter-weibo.html)
   *  - If we assign a different zlevelKey to each series, the "covering issue" above can be resolved,
   *    but having one HTML Canvas per series may be excessively memory-consuming.
   *  Therefore, we only automatically assign zlevelKey on `ScatterSeries` and `LinesSeries` for backward
   *  compatibility, and not to other series. Users can explicitly assign zlevel if they encouter above
   *  "covering issue".
   */
  ComponentModel.prototype.getZLevelKey = function () {
    return '';
  };
  ComponentModel.prototype.setZLevel = function (zlevel) {
    this.option.zlevel = zlevel;
  };
  ComponentModel.protoInitialize = function () {
    var proto = ComponentModel.prototype;
    proto.type = 'component';
    proto.id = '';
    proto.name = '';
    proto.mainType = '';
    proto.subType = '';
    proto.componentIndex = 0;
  }();
  return ComponentModel;
}(Model);
mountExtend(ComponentModel, Model);
enableClassManagement(ComponentModel);
componentUtil.enableSubTypeDefaulter(ComponentModel);
componentUtil.enableTopologicalTravel(ComponentModel, getDependencies);
function getDependencies(componentType) {
  var deps = [];
  zrUtil.each(ComponentModel.getClassesByMainType(componentType), function (clz) {
    deps = deps.concat(clz.dependencies || clz.prototype.dependencies || []);
  });
  // Ensure main type.
  deps = zrUtil.map(deps, function (type) {
    return parseClassType(type).main;
  });
  // Hack dataset for convenience.
  if (componentType !== 'dataset' && zrUtil.indexOf(deps, 'dataset') <= 0) {
    deps.unshift('dataset');
  }
  return deps;
}
export default ComponentModel;
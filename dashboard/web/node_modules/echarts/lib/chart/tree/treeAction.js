
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
import { registerRoamActionSimply } from '../../component/helper/roamHelper.js';
import { COMPONENT_MAIN_TYPE_SERIES } from '../../util/types.js';
import { SERIES_TYPE_TREE } from './TreeSeries.js';
export function installTreeAction(registers) {
  registers.registerAction({
    type: 'treeExpandAndCollapse',
    event: 'treeExpandAndCollapse',
    update: 'update'
  }, function (payload, ecModel) {
    ecModel.eachComponent({
      mainType: COMPONENT_MAIN_TYPE_SERIES,
      subType: SERIES_TYPE_TREE,
      query: payload
    }, function (seriesModel) {
      var dataIndex = payload.dataIndex;
      var tree = seriesModel.getData().tree;
      var node = tree.getNodeByDataIndex(dataIndex);
      node.isExpand = !node.isExpand;
    });
  });
  registerRoamActionSimply(registers, COMPONENT_MAIN_TYPE_SERIES, SERIES_TYPE_TREE);
}
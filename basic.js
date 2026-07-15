function arrToObj(keys, values) {
  const hashObj = {};
  
  for (let i = 0; i < keys.length; i++) {
    hashObj[keys[i]] = values[i];
  }
  
  return hashObj;
}

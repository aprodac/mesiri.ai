import * as React from 'react'
import NetInfo from '@react-native-community/netinfo'

/** Whether the phone has a connection now (true until it is known not to). */
export function useOnline(): boolean {
  const [online, setOnline] = React.useState(true)
  React.useEffect(
    () => NetInfo.addEventListener((s) => setOnline(s.isConnected !== false && s.isInternetReachable !== false)),
    [],
  )
  return online
}

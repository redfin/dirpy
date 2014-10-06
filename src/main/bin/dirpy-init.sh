
PATH=/redfin/dirpy:/sbin:/bin:/usr/bin:/usr/sbin
prog="dirpy"
conf="/redfin/dirpy/dirpy.conf"
user="nobody"
binPath="/redfin/dirpy/dirpy"
pidFile="/redfin/dirpy/run/dirpy.pid"

# Source function library.
. /etc/init.d/functions

if [ "$1" = "status" ] ; then
	status $prog
	RETVAL=$?
	exit $RETVAL
fi

RETVAL=0

start(){
    pidDir=$(dirname $pidFile)
    if [[ ! -d $pidDir ]] ; then
        mkdir -p $pidDir
        chown $user $pidDir
    fi

	echo -n $"Starting $prog: "

	daemon --user=$user $binPath -c $conf
	RETVAL=$?
	echo
	if test $RETVAL = 0 ; then
		touch /redfin/dirpy/run/lock
	fi
	return $RETVAL
}

stop(){
	echo -n $"Stopping $prog: "
	killproc $prog
	RETVAL=$?
	echo
	rm -f /redfin/dirpy/run/lock
	return $RETVAL
}

reload(){
	stop
	start
}

restart(){
	stop
	start
}

condrestart(){
	[ -e /redfin/dirpy/run/lock ] && restart
	return 0
}


case "$1" in
    start)
	start
	;;
    stop)
	stop
	;;
    restart)
	restart
	;;
    reload|force-reload)
	reload
	;;
    condrestart|try-restart)
	condrestart
	;;
    *)
	echo $"Usage: $0 {start|stop|status|restart|condrestart|try-restart|reload|force-reload}"
	RETVAL=3
esac

exit $RETVAL


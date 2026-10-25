'use client';
import {forwardRef,useRef} from 'react';
import * as Dialog from '@radix-ui/react-dialog';

// Async openers are not always a Radix Trigger. Preserve their actual focus
// target while Radix continues to own trapping, dismissal and modal semantics.
export const DialogContent=forwardRef(function DialogContent({onOpenAutoFocus,onCloseAutoFocus,...props},ref){
 const opener=useRef(null);
 return <Dialog.Content {...props} ref={ref}
  onOpenAutoFocus={event=>{
   if(!opener.current)opener.current=document.activeElement;
   onOpenAutoFocus?.(event);
  }}
  onCloseAutoFocus={event=>{
   onCloseAutoFocus?.(event);
   if(!event.defaultPrevented&&opener.current?.isConnected){
    event.preventDefault();opener.current.focus();
   }
   opener.current=null;
  }}/>
});
